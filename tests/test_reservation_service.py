from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db

from app.models import (
    User,
    Reader,
    Book,
    Copy,
    Loan,
    Reservation,
    AuditLog
)

from app.services import (
    ReservationService,
    LoanService,
    CopyService
)

from app.exceptions import (
    ValidationError,
    BusinessRuleError,
    NotFoundError,
    AuthenticationError,
    AuthorizationError,
    InactiveAccountError,
    ReservationLimitExceededError,
    ReservationAlreadyExistsError,
    LoanLimitExceededError,
    CopyUnavailableError
)


# ==========================================
# FIXTURES
# ==========================================

@pytest.fixture
def service(app):

    return ReservationService()


@pytest.fixture
def loan_service(app):

    return LoanService()


@pytest.fixture
def copy_service(app):

    return CopyService()


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

    db.session.add_all([
        admin,
        librarian
    ])

    users = []

    for number in range(1, 6):

        user = User(
            username=f"reader{number}",
            email=f"reader{number}@example.com",
            password_hash="test_hash",
            role="READER",
            is_active=True
        )

        users.append(user)
        db.session.add(user)

    db.session.flush()

    readers = []

    for number, user in enumerate(
        users, start=1
    ):

        reader = Reader(
            user_id=user.id,
            card_number=f"LIB-{number:06d}",
            first_name="Jan",
            last_name="Kowalski"
        )

        readers.append(reader)
        db.session.add(reader)

    books = []

    for number in range(1, 7):

        book = Book(
            title=f"Test book {number}",
            is_archived=False
        )

        books.append(book)
        db.session.add(book)

    db.session.commit()

    return {
        "admin": admin,
        "librarian": librarian,
        "users": users,
        "readers": readers,
        "books": books,
        "user": users[0],
        "reader": readers[0],
        "other_user": users[1],
        "other_reader": readers[1],
        "book": books[0],
        "other_book": books[1]
    }


@pytest.fixture
def copy(copy_service, data):

    return copy_service.create_copy(
        data["admin"].id,
        data["book"].id,
        "INV-001"
    )


@pytest.fixture
def waiting_reservation(service, data):

    return service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )


@pytest.fixture
def ready_reservation(service, data, copy):

    return service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )


# ==========================================
# HELPERS
# ==========================================

def make_expired(service, reservation):

    reservation.expires_at = (
        service.now() - timedelta(minutes=1)
    )

    db.session.commit()

    return reservation


def create_waiting_reservation(
    service,
    book,
    reader,
    reserved_at=None
):

    reservation = Reservation(
        book_id=book.id,
        reader_id=reader.id,
        status="WAITING",
        reserved_at=(
            reserved_at
            if reserved_at is not None
            else service.now()
        ),
        expires_at=None
    )

    db.session.add(reservation)
    db.session.commit()

    return reservation


def count_reserved_copies(book_id):

    return Copy.query.filter_by(
        book_id=book_id,
        status="RESERVED"
    ).count()


def count_ready_reservations(book_id):

    return Reservation.query.filter_by(
        book_id=book_id,
        status="READY"
    ).count()


# ==========================================
# FIXTURE TESTS
# ==========================================

def test_fixture_users(data):

    assert User.query.count() == 7
    assert data["admin"].role == "ADMIN"
    assert data["librarian"].role == "LIBRARIAN"


def test_fixture_readers(data):

    assert Reader.query.count() == 5
    assert len(data["readers"]) == 5

    assert all(
        reader.user.role == "READER"
        for reader in data["readers"]
    )


def test_fixture_books(data):

    assert Book.query.count() == 6

    assert all(
        not book.is_archived
        for book in data["books"]
    )


def test_fixture_copy(copy):

    assert copy.id is not None
    assert copy.status == "AVAILABLE"


def test_fixture_waiting_reservation(
    waiting_reservation
):

    assert waiting_reservation.id is not None
    assert waiting_reservation.status == "WAITING"
    assert waiting_reservation.expires_at is None


def test_fixture_ready_reservation(
    ready_reservation, copy
):

    assert ready_reservation.id is not None
    assert ready_reservation.status == "READY"
    assert ready_reservation.expires_at is not None
    assert copy.status == "RESERVED"


def test_fixture_expired_reservation(
    service, ready_reservation
):

    make_expired(
        service,
        ready_reservation
    )

    assert (
        ready_reservation.expires_at
        < service.now()
    )


def test_fixture_pool_consistency(
    data, ready_reservation
):

    book_id = data["book"].id

    assert count_reserved_copies(book_id) == 1
    assert count_ready_reservations(book_id) == 1

# ==========================================
# CREATE RESERVATION TESTS
# ==========================================

def test_create_reservation_by_admin(
    service, data
):

    reservation = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    assert reservation.id is not None
    assert reservation.status == "WAITING"


def test_create_reservation_by_librarian(
    service, data
):

    reservation = service.create_reservation(
        data["librarian"].id,
        data["reader"].id,
        data["book"].id
    )

    assert reservation.id is not None
    assert reservation.status == "WAITING"


def test_reader_can_create_reservation(
    service, data
):

    reservation = service.create_reservation(
        data["user"].id,
        data["reader"].id,
        data["book"].id
    )

    assert reservation.reader_id == (
        data["reader"].id
    )

    assert reservation.status == "WAITING"


def test_create_own_reservation(
    service, data
):

    reservation = service.create_own_reservation(
        data["user"].id,
        data["book"].id
    )

    assert reservation.id is not None
    assert reservation.reader_id == (
        data["reader"].id
    )

    assert reservation.book_id == (
        data["book"].id
    )


def test_reservation_has_identifier(
    waiting_reservation
):

    assert type(waiting_reservation.id) is int
    assert waiting_reservation.id > 0


def test_reservation_book_relationship(
    data, waiting_reservation
):

    assert waiting_reservation.book_id == (
        data["book"].id
    )

    assert waiting_reservation.book == (
        data["book"]
    )


def test_reservation_reader_relationship(
    data, waiting_reservation
):

    assert waiting_reservation.reader_id == (
        data["reader"].id
    )

    assert waiting_reservation.reader == (
        data["reader"]
    )


def test_reservation_creation_date(
    service, data
):

    before = service.now()

    reservation = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    after = service.now()

    assert reservation.reserved_at is not None

    assert (
        before
        <= reservation.reserved_at
        <= after
    )


def test_reservation_without_available_copy(
    service, data
):

    reservation = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    assert reservation.status == "WAITING"
    assert reservation.expires_at is None

    assert count_reserved_copies(
        data["book"].id
    ) == 0


def test_reservation_with_available_copy(
    service, data, copy
):

    reservation = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    assert reservation.status == "READY"
    assert reservation.expires_at is not None
    assert copy.status == "RESERVED"

    assert count_reserved_copies(
        data["book"].id
    ) == 1

    assert count_ready_reservations(
        data["book"].id
    ) == 1


def test_default_reservation_period(
    service, data, copy
):

    before = service.now()

    reservation = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    after = service.now()

    assert reservation.status == "READY"

    assert (
        before + timedelta(days=3)
        <= reservation.expires_at
        <= after + timedelta(days=3)
    )


def test_custom_reservation_period(
    service, data, copy
):

    service.setting_service.update(
        "RESERVATION_PERIOD_DAYS",
        7
    )

    before = service.now()

    reservation = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    after = service.now()

    assert reservation.status == "READY"

    assert (
        before + timedelta(days=7)
        <= reservation.expires_at
        <= after + timedelta(days=7)
    )


def test_reservations_for_different_books(
    service, data, copy
):

    first = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    second = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["other_book"].id
    )

    assert first.id != second.id
    assert first.status == "READY"
    assert second.status == "WAITING"

    assert first.book_id != second.book_id
    assert first.reader_id == second.reader_id


def test_reservation_preserves_surplus_copies(
    service, copy_service, data
):

    copies = []

    for number in range(1, 4):

        copy = copy_service.create_copy(
            data["admin"].id,
            data["book"].id,
            f"INV-{number:03d}"
        )

        copies.append(copy)

    reservation = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    reserved = [
        copy
        for copy in copies
        if copy.status == "RESERVED"
    ]

    available = [
        copy
        for copy in copies
        if copy.status == "AVAILABLE"
    ]

    assert reservation.status == "READY"
    assert len(reserved) == 1
    assert len(available) == 2


def test_reservation_persisted_in_database(
    service, data
):

    reservation = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    reservation_id = reservation.id
    reader_id = data["reader"].id
    book_id = data["book"].id

    db.session.remove()

    saved = db.session.get(
        Reservation,
        reservation_id
    )

    assert saved is not None
    assert saved.id == reservation_id
    assert saved.reader_id == reader_id
    assert saved.book_id == book_id
    assert saved.status == "WAITING"


# ==========================================
# VALIDATION TESTS
# ==========================================

@pytest.mark.parametrize(
    "invalid_id",
    [None, 0, -1, True, "1", 1.5]
)
def test_invalid_reservation_reader_id(
    service, data, invalid_id
):

    with pytest.raises(ValidationError):

        service.create_reservation(
            data["admin"].id,
            invalid_id,
            data["book"].id
        )

    assert Reservation.query.count() == 0


@pytest.mark.parametrize(
    "invalid_id",
    [None, 0, -1, True, "1", 1.5]
)
def test_invalid_reservation_book_id(
    service, data, invalid_id
):

    with pytest.raises(ValidationError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            invalid_id
        )

    assert Reservation.query.count() == 0


@pytest.mark.parametrize(
    "invalid_id",
    [None, 0, -1, True, "1", 1.5]
)
def test_invalid_reservation_id(
    service, data, invalid_id
):

    with pytest.raises(ValidationError):

        service.get_by_id(
            data["admin"].id,
            invalid_id
        )


@pytest.mark.parametrize(
    "invalid_status",
    [None, "", "   ", 123, True, "UNKNOWN"]
)
def test_invalid_reservation_status(
    service, data, invalid_status
):

    with pytest.raises(ValidationError):

        service.get_by_status(
            data["admin"].id,
            invalid_status
        )


# ==========================================
# NOT FOUND TESTS
# ==========================================

def test_reservation_nonexistent_reader(
    service, data
):

    with pytest.raises(
        AuthorizationError,
        match="Access denied"
    ):

        service.create_reservation(
            data["admin"].id,
            99999,
            data["book"].id
        )

    assert Reservation.query.count() == 0

def test_reservation_nonexistent_book(
    service, data
):

    with pytest.raises(NotFoundError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            99999
        )

    assert Reservation.query.count() == 0


def test_nonexistent_reservation(
    service, data
):

    with pytest.raises(NotFoundError):

        service.get_by_id(
            data["admin"].id,
            99999
        )


# ==========================================
# AUTHENTICATION TESTS
# ==========================================

def test_unauthenticated_reservation_creation(
    service, data
):

    with pytest.raises(AuthenticationError):

        service.create_reservation(
            None,
            data["reader"].id,
            data["book"].id
        )

    assert Reservation.query.count() == 0


def test_unknown_actor_cannot_create_reservation(
    service, data
):

    with pytest.raises(AuthenticationError):

        service.create_reservation(
            99999,
            data["reader"].id,
            data["book"].id
        )

    assert Reservation.query.count() == 0


# ==========================================
# INACTIVE ACCOUNT TESTS
# ==========================================

def test_inactive_admin_cannot_create_reservation(
    service, data
):

    data["admin"].is_active = False

    db.session.commit()

    with pytest.raises(InactiveAccountError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            data["book"].id
        )

    assert Reservation.query.count() == 0


def test_inactive_reader_cannot_create_reservation(
    service, data
):

    data["user"].is_active = False

    db.session.commit()

    with pytest.raises(InactiveAccountError):

        service.create_reservation(
            data["user"].id,
            data["reader"].id,
            data["book"].id
        )

    assert Reservation.query.count() == 0


def test_staff_cannot_reserve_for_inactive_reader(
    service, data
):

    data["user"].is_active = False

    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            data["book"].id
        )

    assert Reservation.query.count() == 0


# ==========================================
# AUTHORIZATION TESTS
# ==========================================

def test_reader_cannot_reserve_for_another_reader(
    service, data
):

    with pytest.raises(AuthorizationError):

        service.create_reservation(
            data["user"].id,
            data["other_reader"].id,
            data["book"].id
        )

    assert Reservation.query.count() == 0


def test_reader_cannot_read_other_reservation(
    service, data, waiting_reservation
):

    with pytest.raises(AuthorizationError):

        service.get_by_id(
            data["other_user"].id,
            waiting_reservation.id
        )


def test_reader_cannot_list_all_reservations(
    service, data
):

    with pytest.raises(AuthorizationError):

        service.get_all(
            data["user"].id
        )


def test_reader_cannot_process_queue(
    service, data
):

    with pytest.raises(AuthorizationError):

        service.process_queue(
            data["user"].id,
            data["book"].id
        )


def test_reader_cannot_read_other_reservation_history(
    service, data
):

    with pytest.raises(AuthorizationError):

        service.get_by_reader(
            data["user"].id,
            data["other_reader"].id
        )


# ==========================================
# ARCHIVED BOOK TESTS
# ==========================================

def test_cannot_reserve_archived_book(
    service, data
):

    data["book"].is_archived = True

    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            data["book"].id
        )

    assert Reservation.query.count() == 0



# ==========================================
# RESERVATION LIMIT TESTS
# ==========================================

def test_default_reservation_limit(
    service, data
):

    for book in data["books"][:3]:

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            book.id
        )

    assert Reservation.query.count() == 3

    with pytest.raises(ReservationLimitExceededError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            data["books"][3].id
        )

    assert Reservation.query.count() == 3


def test_custom_reservation_limit(
    service, data
):

    service.setting_service.update(
        "MAX_ACTIVE_RESERVATIONS",
        1
    )

    service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    with pytest.raises(ReservationLimitExceededError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            data["other_book"].id
        )

    assert Reservation.query.count() == 1


def test_increased_reservation_limit(
    service, data
):

    service.setting_service.update(
        "MAX_ACTIVE_RESERVATIONS",
        5
    )

    for book in data["books"][:5]:

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            book.id
        )

    assert Reservation.query.count() == 5

    with pytest.raises(ReservationLimitExceededError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            data["books"][5].id
        )


def test_waiting_reservation_counts_towards_limit(
    service, data, waiting_reservation
):

    service.setting_service.update(
        "MAX_ACTIVE_RESERVATIONS",
        1
    )

    assert waiting_reservation.status == "WAITING"

    with pytest.raises(ReservationLimitExceededError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            data["other_book"].id
        )


def test_ready_reservation_counts_towards_limit(
    service, data, ready_reservation
):

    service.setting_service.update(
        "MAX_ACTIVE_RESERVATIONS",
        1
    )

    assert ready_reservation.status == "READY"

    with pytest.raises(ReservationLimitExceededError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            data["other_book"].id
        )


@pytest.mark.parametrize(
    "status",
    ["FULFILLED", "CANCELLED", "EXPIRED"]
)
def test_inactive_reservation_does_not_count(
    service, data, status
):

    service.setting_service.update(
        "MAX_ACTIVE_RESERVATIONS",
        1
    )

    reservation = Reservation(
        book_id=data["book"].id,
        reader_id=data["reader"].id,
        status=status,
        reserved_at=service.now()
    )

    db.session.add(reservation)
    db.session.commit()

    result = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["other_book"].id
    )

    assert result.status == "WAITING"
    assert Reservation.query.count() == 2


def test_mixed_active_reservation_limit(
    service, data, copy
):

    first = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    second = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["books"][1].id
    )

    third = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["books"][2].id
    )

    assert first.status == "READY"
    assert second.status == "WAITING"
    assert third.status == "WAITING"

    with pytest.raises(ReservationLimitExceededError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            data["books"][3].id
        )


def test_reservation_limits_are_independent(
    service, data
):

    service.setting_service.update(
        "MAX_ACTIVE_RESERVATIONS",
        1
    )

    first = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    second = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["other_book"].id
    )

    assert first.id != second.id
    assert first.status == "WAITING"
    assert second.status == "WAITING"

    assert Reservation.query.count() == 2


def test_cancellation_frees_reservation_limit(
    service, data, waiting_reservation
):

    service.setting_service.update(
        "MAX_ACTIVE_RESERVATIONS",
        1
    )

    service.cancel_reservation(
        data["admin"].id,
        waiting_reservation.id
    )

    result = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["other_book"].id
    )

    assert waiting_reservation.status == "CANCELLED"
    assert result.status == "WAITING"


def test_remaining_reservation_limit(
    service, data, waiting_reservation
):

    remaining = service.get_remaining_reservation_limit(
        data["admin"].id,
        data["reader"].id
    )

    assert remaining == 2


def test_remaining_reservation_limit_at_zero(
    service, data
):

    service.setting_service.update(
        "MAX_ACTIVE_RESERVATIONS",
        1
    )

    service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    remaining = service.get_remaining_reservation_limit(
        data["admin"].id,
        data["reader"].id
    )

    assert remaining == 0


def test_remaining_limit_after_setting_reduction(
    service, data
):

    for book in data["books"][:3]:

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            book.id
        )

    service.setting_service.update(
        "MAX_ACTIVE_RESERVATIONS",
        1
    )

    remaining = service.get_remaining_reservation_limit(
        data["admin"].id,
        data["reader"].id
    )

    assert remaining == 0
    assert Reservation.query.count() == 3


# ==========================================
# DUPLICATE RESERVATION TESTS
# ==========================================

def test_duplicate_waiting_reservation(
    service, data, waiting_reservation
):

    with pytest.raises(ReservationAlreadyExistsError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            data["book"].id
        )

    assert Reservation.query.count() == 1
    assert waiting_reservation.status == "WAITING"


def test_duplicate_ready_reservation(
    service, data, ready_reservation, copy
):

    with pytest.raises(ReservationAlreadyExistsError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            data["book"].id
        )

    assert Reservation.query.count() == 1
    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"


def test_duplicate_own_reservation(
    service, data, waiting_reservation
):

    with pytest.raises(ReservationAlreadyExistsError):

        service.create_own_reservation(
            data["user"].id,
            data["book"].id
        )

    assert Reservation.query.count() == 1


def test_multiple_readers_can_reserve_same_book(
    service, data
):

    first = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    second = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["book"].id
    )

    assert first.id != second.id
    assert first.reader_id != second.reader_id
    assert first.book_id == second.book_id

    assert first.status == "WAITING"
    assert second.status == "WAITING"


@pytest.mark.parametrize(
    "status",
    ["FULFILLED", "CANCELLED", "EXPIRED"]
)
def test_can_reserve_after_inactive_reservation(
    service, data, status
):

    previous = Reservation(
        book_id=data["book"].id,
        reader_id=data["reader"].id,
        status=status,
        reserved_at=service.now()
    )

    db.session.add(previous)
    db.session.commit()

    result = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    assert result.id != previous.id
    assert result.status == "WAITING"
    assert previous.status == status

    assert Reservation.query.count() == 2


def test_can_reserve_again_after_cancellation(
    service, data, waiting_reservation
):

    service.cancel_reservation(
        data["admin"].id,
        waiting_reservation.id
    )

    result = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    assert waiting_reservation.status == "CANCELLED"
    assert result.status == "WAITING"
    assert result.id != waiting_reservation.id


# ==========================================
# ACTIVE LOAN PROTECTION TESTS
# ==========================================

def test_cannot_reserve_currently_borrowed_book(
    service, loan_service, data, copy
):

    loan = loan_service.borrow_book(
        data["admin"].id,
        data["reader"].id,
        copy.id
    )

    with pytest.raises(BusinessRuleError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            data["book"].id
        )

    assert loan.status == "ACTIVE"
    assert copy.status == "LOANED"
    assert Reservation.query.count() == 0


def test_can_reserve_different_book_with_active_loan(
    service, loan_service, data, copy
):

    loan = loan_service.borrow_book(
        data["admin"].id,
        data["reader"].id,
        copy.id
    )

    reservation = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["other_book"].id
    )

    assert loan.status == "ACTIVE"
    assert reservation.status == "WAITING"

    assert reservation.book_id != copy.book_id


def test_other_reader_can_reserve_borrowed_book(
    service, loan_service, data, copy
):

    loan_service.borrow_book(
        data["admin"].id,
        data["reader"].id,
        copy.id
    )

    reservation = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["book"].id
    )

    assert reservation.status == "WAITING"
    assert copy.status == "LOANED"

    assert reservation.reader_id == (
        data["other_reader"].id
    )


def test_can_reserve_previously_returned_book(
    service, loan_service, data, copy
):

    loan = loan_service.borrow_book(
        data["admin"].id,
        data["reader"].id,
        copy.id
    )

    loan_service.return_book(
        data["admin"].id,
        loan.id
    )

    reservation = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    assert loan.status == "RETURNED"
    assert reservation.status == "READY"
    assert copy.status == "RESERVED"


def test_can_reserve_after_cancelled_loan(
    service, loan_service, data, copy
):

    loan = loan_service.borrow_book(
        data["admin"].id,
        data["reader"].id,
        copy.id
    )

    loan_service.cancel_loan(
        data["admin"].id,
        loan.id,
        "Incorrect registration"
    )

    reservation = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    assert loan.status == "CANCELLED"
    assert reservation.status == "READY"
    assert copy.status == "RESERVED"




# ==========================================
# FIFO QUEUE TESTS
# ==========================================

def test_process_empty_queue(
    service, data
):

    result = service.process_queue(
        data["admin"].id,
        data["book"].id
    )

    assert result == []
    assert Reservation.query.count() == 0


def test_process_queue_without_available_copies(
    service, data, waiting_reservation
):

    result = service.process_queue(
        data["admin"].id,
        data["book"].id
    )

    assert result == []
    assert waiting_reservation.status == "WAITING"
    assert waiting_reservation.expires_at is None


def test_process_first_waiting_reservation(
    service, data, copy
):

    reservation = create_waiting_reservation(
        service,
        data["book"],
        data["reader"]
    )

    result = service.process_queue(
        data["admin"].id,
        data["book"].id
    )

    assert len(result) == 1
    assert result[0].id == reservation.id
    assert reservation.status == "READY"
    assert reservation.expires_at is not None
    assert copy.status == "RESERVED"


def test_fifo_order_by_reservation_date(
    service, data, copy
):

    now = service.now()

    newer = create_waiting_reservation(
        service,
        data["book"],
        data["other_reader"],
        now - timedelta(hours=1)
    )

    older = create_waiting_reservation(
        service,
        data["book"],
        data["reader"],
        now - timedelta(hours=2)
    )

    assert newer.id < older.id

    result = service.process_queue(
        data["admin"].id,
        data["book"].id
    )

    assert len(result) == 1
    assert result[0].id == older.id

    assert older.status == "READY"
    assert newer.status == "WAITING"
    assert copy.status == "RESERVED"


def test_fifo_order_by_id_when_dates_equal(
    service, data, copy
):

    now = service.now()

    first = create_waiting_reservation(
        service,
        data["book"],
        data["reader"],
        now
    )

    second = create_waiting_reservation(
        service,
        data["book"],
        data["other_reader"],
        now
    )

    assert first.id < second.id

    assert first.reserved_at == (
        second.reserved_at
    )

    result = service.process_queue(
        data["admin"].id,
        data["book"].id
    )

    assert len(result) == 1
    assert result[0].id == first.id

    assert first.status == "READY"
    assert second.status == "WAITING"


def test_process_multiple_waiting_reservations(
    service, copy_service, data
):

    copies = []

    for number in range(1, 4):

        copy = copy_service.create_copy(
            data["admin"].id,
            data["book"].id,
            f"INV-{number:03d}"
        )

        copies.append(copy)

    reservations = []

    now = service.now()

    for index, reader in enumerate(
        data["readers"][:4]
    ):

        reservation = create_waiting_reservation(
            service,
            data["book"],
            reader,
            now + timedelta(seconds=index)
        )

        reservations.append(reservation)

    result = service.process_queue(
        data["admin"].id,
        data["book"].id
    )

    assert len(result) == 3

    assert [item.id for item in result] == [
        item.id for item in reservations[:3]
    ]

    assert all(
        reservation.status == "READY"
        for reservation in reservations[:3]
    )

    assert reservations[3].status == "WAITING"

    assert all(
        copy.status == "RESERVED"
        for copy in copies
    )

    assert count_reserved_copies(
        data["book"].id
    ) == 3

    assert count_ready_reservations(
        data["book"].id
    ) == 3


# ==========================================
# QUEUE POSITION TESTS
# ==========================================

def test_first_queue_position(
    service, data, waiting_reservation
):

    position = service.get_queue_position(
        data["admin"].id,
        waiting_reservation.id
    )

    assert position == 1


def test_second_queue_position(
    service, data, waiting_reservation
):

    second = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["book"].id
    )

    position = service.get_queue_position(
        data["admin"].id,
        second.id
    )

    assert position == 2


def test_third_queue_position(
    service, data
):

    reservations = []

    for reader in data["readers"][:3]:

        reservation = service.create_reservation(
            data["admin"].id,
            reader.id,
            data["book"].id
        )

        reservations.append(reservation)

    position = service.get_queue_position(
        data["admin"].id,
        reservations[2].id
    )

    assert position == 3


def test_ready_reservation_queue_position(
    service, data, ready_reservation
):

    position = service.get_queue_position(
        data["admin"].id,
        ready_reservation.id
    )

    assert position == 0


@pytest.mark.parametrize(
    "status",
    ["FULFILLED", "CANCELLED", "EXPIRED"]
)
def test_inactive_reservation_has_no_position(
    service, data, status
):

    reservation = Reservation(
        reader_id=data["reader"].id,
        book_id=data["book"].id,
        status=status,
        reserved_at=service.now()
    )

    db.session.add(reservation)
    db.session.commit()

    position = service.get_queue_position(
        data["admin"].id,
        reservation.id
    )

    assert position is None


def test_queue_position_after_cancellation(
    service, data, waiting_reservation
):

    second = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["book"].id
    )

    assert service.get_queue_position(
        data["admin"].id,
        second.id
    ) == 2

    service.cancel_reservation(
        data["admin"].id,
        waiting_reservation.id
    )

    assert waiting_reservation.status == (
        "CANCELLED"
    )

    assert service.get_queue_position(
        data["admin"].id,
        second.id
    ) == 1


# ==========================================
# QUEUE INDEPENDENCE TESTS
# ==========================================

def test_reservation_queues_are_independent(
    service, copy_service, data
):

    first = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    second = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["other_book"].id
    )

    copy = copy_service.create_copy(
        data["admin"].id,
        data["book"].id,
        "INV-001"
    )

    assert first.status == "READY"
    assert second.status == "WAITING"
    assert copy.status == "RESERVED"

    assert service.get_queue_position(
        data["admin"].id,
        first.id
    ) == 0

    assert service.get_queue_position(
        data["admin"].id,
        second.id
    ) == 1


# ==========================================
# INACTIVE READER QUEUE TESTS
# ==========================================

def test_queue_skips_inactive_reader(
    service, data, copy
):

    now = service.now()

    first = create_waiting_reservation(
        service,
        data["book"],
        data["reader"],
        now - timedelta(hours=2)
    )

    second = create_waiting_reservation(
        service,
        data["book"],
        data["other_reader"],
        now - timedelta(hours=1)
    )

    data["user"].is_active = False
    db.session.commit()

    result = service.process_queue(
        data["admin"].id,
        data["book"].id
    )

    assert first.status == "CANCELLED"
    assert second.status == "READY"
    assert copy.status == "RESERVED"

    assert len(result) == 1
    assert result[0].id == second.id


# ==========================================
# QUEUE IDEMPOTENCY TESTS
# ==========================================

def test_process_queue_is_idempotent(
    service, data, ready_reservation, copy
):

    original_expiry = (
        ready_reservation.expires_at
    )

    first = service.process_queue(
        data["admin"].id,
        data["book"].id
    )

    second = service.process_queue(
        data["admin"].id,
        data["book"].id
    )

    assert first == []
    assert second == []

    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"

    assert ready_reservation.expires_at == (
        original_expiry
    )

    assert AuditLog.query.filter_by(
        action="RESERVATION_READY"
    ).count() == 1


# ==========================================
# QUEUE AUTHORIZATION TESTS
# ==========================================

def test_librarian_can_process_queue(
    service, data, copy
):

    reservation = create_waiting_reservation(
        service,
        data["book"],
        data["reader"]
    )

    result = service.process_queue(
        data["librarian"].id,
        data["book"].id
    )

    assert len(result) == 1
    assert reservation.status == "READY"
    assert copy.status == "RESERVED"


def test_cannot_process_archived_book_queue(
    service, data
):

    data["book"].is_archived = True
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.process_queue(
            data["admin"].id,
            data["book"].id
        )


def test_reader_cannot_get_other_queue_position(
    service, data, waiting_reservation
):

    with pytest.raises(AuthorizationError):

        service.get_queue_position(
            data["other_user"].id,
            waiting_reservation.id
        )



# ==========================================
# CANCELLATION TESTS
# ==========================================

def test_cancel_waiting_reservation(
    service, data, waiting_reservation
):

    result = service.cancel_reservation(
        data["admin"].id,
        waiting_reservation.id
    )

    assert result.id == waiting_reservation.id
    assert result.status == "CANCELLED"
    assert result.expires_at is None
    assert Reservation.query.count() == 1


def test_cancel_ready_reservation(
    service, data, ready_reservation, copy
):

    result = service.cancel_reservation(
        data["admin"].id,
        ready_reservation.id
    )

    assert result.status == "CANCELLED"
    assert copy.status == "AVAILABLE"

    assert count_reserved_copies(
        data["book"].id
    ) == 0

    assert count_ready_reservations(
        data["book"].id
    ) == 0


def test_librarian_can_cancel_reservation(
    service, data, waiting_reservation
):

    result = service.cancel_reservation(
        data["librarian"].id,
        waiting_reservation.id
    )

    assert result.status == "CANCELLED"


def test_reader_can_cancel_own_waiting_reservation(
    service, data, waiting_reservation
):

    result = service.cancel_reservation(
        data["user"].id,
        waiting_reservation.id
    )

    assert result.status == "CANCELLED"


def test_reader_can_cancel_own_ready_reservation(
    service, data, ready_reservation, copy
):

    result = service.cancel_reservation(
        data["user"].id,
        ready_reservation.id
    )

    assert result.status == "CANCELLED"
    assert copy.status == "AVAILABLE"


def test_reader_cannot_cancel_other_reservation(
    service, data, waiting_reservation
):

    with pytest.raises(AuthorizationError):

        service.cancel_reservation(
            data["other_user"].id,
            waiting_reservation.id
        )

    assert waiting_reservation.status == "WAITING"


def test_unauthenticated_cancellation(
    service, waiting_reservation
):

    with pytest.raises(AuthenticationError):

        service.cancel_reservation(
            None,
            waiting_reservation.id
        )

    assert waiting_reservation.status == "WAITING"


def test_inactive_reader_cannot_cancel_reservation(
    service, data, waiting_reservation
):

    data["user"].is_active = False
    db.session.commit()

    with pytest.raises(InactiveAccountError):

        service.cancel_reservation(
            data["user"].id,
            waiting_reservation.id
        )

    assert waiting_reservation.status == "WAITING"


def test_staff_can_cancel_inactive_reader_reservation(
    service, data, waiting_reservation
):

    data["user"].is_active = False
    db.session.commit()

    result = service.cancel_reservation(
        data["admin"].id,
        waiting_reservation.id
    )

    assert result.status == "CANCELLED"


# ==========================================
# CANCELLATION VALIDATION
# ==========================================

@pytest.mark.parametrize(
    "invalid_id",
    [None, 0, -1, True, "1", 1.5]
)
def test_cancel_invalid_reservation_id(
    service, data, invalid_id
):

    with pytest.raises(ValidationError):

        service.cancel_reservation(
            data["admin"].id,
            invalid_id
        )


def test_cancel_nonexistent_reservation(
    service, data
):

    with pytest.raises(NotFoundError):

        service.cancel_reservation(
            data["admin"].id,
            99999
        )


@pytest.mark.parametrize(
    "status",
    ["FULFILLED", "CANCELLED", "EXPIRED"]
)
def test_cannot_cancel_inactive_reservation(
    service, data, status
):

    reservation = Reservation(
        book_id=data["book"].id,
        reader_id=data["reader"].id,
        reserved_at=service.now(),
        status=status
    )

    db.session.add(reservation)
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.cancel_reservation(
            data["admin"].id,
            reservation.id
        )

    assert reservation.status == status


def test_cannot_cancel_reservation_twice(
    service, data, waiting_reservation
):

    service.cancel_reservation(
        data["admin"].id,
        waiting_reservation.id
    )

    with pytest.raises(BusinessRuleError):

        service.cancel_reservation(
            data["admin"].id,
            waiting_reservation.id
        )

    assert waiting_reservation.status == "CANCELLED"

    assert AuditLog.query.filter_by(
        action="RESERVATION_CANCELLED"
    ).count() == 1


def test_cannot_cancel_expired_ready_reservation(
    service, data, ready_reservation, copy
):

    make_expired(
        service,
        ready_reservation
    )

    with pytest.raises(BusinessRuleError):

        service.cancel_reservation(
            data["admin"].id,
            ready_reservation.id
        )

    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"


# ==========================================
# CANCELLATION QUEUE INTEGRATION
# ==========================================

def test_cancellation_releases_copy_to_next_reader(
    service, data, ready_reservation, copy
):

    second = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["book"].id
    )

    assert second.status == "WAITING"

    service.cancel_reservation(
        data["admin"].id,
        ready_reservation.id
    )

    assert ready_reservation.status == "CANCELLED"
    assert second.status == "READY"
    assert second.expires_at is not None
    assert copy.status == "RESERVED"

    assert count_reserved_copies(
        data["book"].id
    ) == 1

    assert count_ready_reservations(
        data["book"].id
    ) == 1


def test_cancellation_respects_fifo(
    service, data, ready_reservation, copy
):

    second = service.create_reservation(
        data["admin"].id,
        data["readers"][1].id,
        data["book"].id
    )

    third = service.create_reservation(
        data["admin"].id,
        data["readers"][2].id,
        data["book"].id
    )

    service.cancel_reservation(
        data["admin"].id,
        ready_reservation.id
    )

    assert ready_reservation.status == "CANCELLED"
    assert second.status == "READY"
    assert third.status == "WAITING"
    assert copy.status == "RESERVED"

    assert service.get_queue_position(
        data["admin"].id,
        third.id
    ) == 1


def test_cancel_waiting_preserves_ready_reservation(
    service, data, ready_reservation, copy
):

    second = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["book"].id
    )

    original_expiry = ready_reservation.expires_at

    service.cancel_reservation(
        data["admin"].id,
        second.id
    )

    assert second.status == "CANCELLED"
    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"

    assert ready_reservation.expires_at == (
        original_expiry
    )


def test_cancellation_sets_new_pickup_period(
    service, data, ready_reservation, copy
):

    second = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["book"].id
    )

    service.setting_service.update(
        "RESERVATION_PERIOD_DAYS",
        7
    )

    before = service.now()

    service.cancel_reservation(
        data["admin"].id,
        ready_reservation.id
    )

    after = service.now()

    assert second.status == "READY"

    assert (
        before + timedelta(days=7)
        <= second.expires_at
        <= after + timedelta(days=7)
    )


def test_cancellation_preserves_other_book_queue(
    service, data, ready_reservation, copy
):

    other = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["other_book"].id
    )

    service.cancel_reservation(
        data["admin"].id,
        ready_reservation.id
    )

    assert ready_reservation.status == "CANCELLED"
    assert other.status == "WAITING"
    assert other.expires_at is None
    assert copy.status == "AVAILABLE"


# ==========================================
# CANCELLATION AUDIT
# ==========================================

def test_cancellation_audit(
    service, data, waiting_reservation
):

    service.cancel_reservation(
        data["admin"].id,
        waiting_reservation.id
    )

    log = AuditLog.query.filter_by(
        action="RESERVATION_CANCELLED"
    ).one()

    assert log.user_id == data["admin"].id

    assert str(
        waiting_reservation.id
    ) in log.description


def test_reader_cancellation_audit(
    service, data, waiting_reservation
):

    service.cancel_reservation(
        data["user"].id,
        waiting_reservation.id
    )

    log = AuditLog.query.filter_by(
        action="RESERVATION_CANCELLED"
    ).one()

    assert log.user_id == data["user"].id


# ==========================================
# CANCELLATION TRANSACTION TESTS
# ==========================================

def test_cancellation_audit_rollback(
    service, data, ready_reservation,
    copy, monkeypatch
):

    original_log = service.audit_service.log

    def fail_cancellation_audit(
        action, *args, **kwargs
    ):

        if action == "RESERVATION_CANCELLED":

            raise RuntimeError(
                "Simulated cancellation audit failure."
            )

        return original_log(
            action, *args, **kwargs
        )

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_cancellation_audit
    )

    with pytest.raises(RuntimeError):

        service.cancel_reservation(
            data["admin"].id,
            ready_reservation.id
        )

    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"

    assert AuditLog.query.filter_by(
        action="RESERVATION_CANCELLED"
    ).count() == 0


def test_cancellation_queue_rollback(
    service, data, ready_reservation,
    copy, monkeypatch
):

    second = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["book"].id
    )

    original_process = service._process_queue

    def fail_queue(*args, **kwargs):

        original_process(*args, **kwargs)

        raise RuntimeError(
            "Simulated reservation queue failure."
        )

    monkeypatch.setattr(
        service,
        "_process_queue",
        fail_queue
    )

    with pytest.raises(RuntimeError):

        service.cancel_reservation(
            data["admin"].id,
            ready_reservation.id
        )

    assert ready_reservation.status == "READY"
    assert second.status == "WAITING"
    assert second.expires_at is None
    assert copy.status == "RESERVED"

    assert count_reserved_copies(
        data["book"].id
    ) == 1

    assert count_ready_reservations(
        data["book"].id
    ) == 1

    assert AuditLog.query.filter_by(
        action="RESERVATION_CANCELLED"
    ).count() == 0

    assert AuditLog.query.filter_by(
        action="RESERVATION_READY"
    ).count() == 1



# ==========================================
# EXPIRATION TESTS
# ==========================================

def test_expire_empty_reservation_collection(
    service, data
):

    result = service.expire_reservations(
        data["admin"].id
    )

    assert result == []
    assert Reservation.query.count() == 0


def test_expire_ready_reservation(
    service, data, ready_reservation, copy
):

    make_expired(
        service,
        ready_reservation
    )

    result = service.expire_reservations(
        data["admin"].id
    )

    assert len(result) == 1
    assert result[0].id == ready_reservation.id
    assert ready_reservation.status == "EXPIRED"
    assert copy.status == "AVAILABLE"


def test_unexpired_reservation_is_preserved(
    service, data, ready_reservation, copy
):

    original_expiry = ready_reservation.expires_at

    result = service.expire_reservations(
        data["admin"].id
    )

    assert result == []
    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"

    assert ready_reservation.expires_at == (
        original_expiry
    )


def test_waiting_reservation_does_not_expire(
    service, data, waiting_reservation
):

    waiting_reservation.reserved_at = (
        service.now() - timedelta(days=365)
    )

    db.session.commit()

    result = service.expire_reservations(
        data["admin"].id
    )

    assert result == []
    assert waiting_reservation.status == "WAITING"
    assert waiting_reservation.expires_at is None


@pytest.mark.parametrize(
    "status",
    ["FULFILLED", "CANCELLED", "EXPIRED"]
)
def test_expiration_ignores_inactive_reservations(
    service, data, status
):

    reservation = Reservation(
        book_id=data["book"].id,
        reader_id=data["reader"].id,
        reserved_at=(
            service.now() - timedelta(days=10)
        ),
        expires_at=(
            service.now() - timedelta(days=5)
        ),
        status=status
    )

    db.session.add(reservation)
    db.session.commit()

    result = service.expire_reservations(
        data["admin"].id
    )

    assert result == []
    assert reservation.status == status


def test_expiration_preserves_original_deadline(
    service, data, ready_reservation
):

    make_expired(
        service,
        ready_reservation
    )

    original_expiry = ready_reservation.expires_at

    service.expire_reservations(
        data["admin"].id
    )

    assert ready_reservation.status == "EXPIRED"

    assert ready_reservation.expires_at == (
        original_expiry
    )


def test_expiration_does_not_delete_reservation(
    service, data, ready_reservation
):

    reservation_id = ready_reservation.id

    make_expired(
        service,
        ready_reservation
    )

    service.expire_reservations(
        data["admin"].id
    )

    saved = db.session.get(
        Reservation,
        reservation_id
    )

    assert saved is not None
    assert saved.status == "EXPIRED"
    assert Reservation.query.count() == 1


# ==========================================
# EXPIRATION AUTHORIZATION TESTS
# ==========================================

def test_librarian_can_expire_reservations(
    service, data, ready_reservation
):

    make_expired(
        service,
        ready_reservation
    )

    result = service.expire_reservations(
        data["librarian"].id
    )

    assert len(result) == 1
    assert ready_reservation.status == "EXPIRED"


def test_reader_cannot_expire_reservations(
    service, data, ready_reservation, copy
):

    make_expired(
        service,
        ready_reservation
    )

    with pytest.raises(AuthorizationError):

        service.expire_reservations(
            data["user"].id
        )

    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"


def test_unauthenticated_expiration(
    service, ready_reservation
):

    make_expired(
        service,
        ready_reservation
    )

    with pytest.raises(AuthenticationError):

        service.expire_reservations(None)

    assert ready_reservation.status == "READY"


def test_inactive_admin_cannot_expire_reservations(
    service, data, ready_reservation
):

    make_expired(
        service,
        ready_reservation
    )

    data["admin"].is_active = False
    db.session.commit()

    with pytest.raises(InactiveAccountError):

        service.expire_reservations(
            data["admin"].id
        )

    assert ready_reservation.status == "READY"


# ==========================================
# EXPIRATION QUEUE INTEGRATION
# ==========================================

def test_expiration_releases_copy_to_next_reader(
    service, data, ready_reservation, copy
):

    second = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["book"].id
    )

    assert second.status == "WAITING"

    make_expired(
        service,
        ready_reservation
    )

    result = service.expire_reservations(
        data["admin"].id
    )

    assert len(result) == 1
    assert ready_reservation.status == "EXPIRED"
    assert second.status == "READY"
    assert second.expires_at is not None
    assert copy.status == "RESERVED"

    assert count_reserved_copies(
        data["book"].id
    ) == 1

    assert count_ready_reservations(
        data["book"].id
    ) == 1


def test_expiration_respects_fifo(
    service, data, ready_reservation, copy
):

    second = service.create_reservation(
        data["admin"].id,
        data["readers"][1].id,
        data["book"].id
    )

    third = service.create_reservation(
        data["admin"].id,
        data["readers"][2].id,
        data["book"].id
    )

    make_expired(
        service,
        ready_reservation
    )

    service.expire_reservations(
        data["admin"].id
    )

    assert ready_reservation.status == "EXPIRED"
    assert second.status == "READY"
    assert third.status == "WAITING"
    assert copy.status == "RESERVED"


def test_expiration_sets_new_pickup_deadline(
    service, data, ready_reservation
):

    second = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["book"].id
    )

    service.setting_service.update(
        "RESERVATION_PERIOD_DAYS",
        7
    )

    make_expired(
        service,
        ready_reservation
    )

    before = service.now()

    service.expire_reservations(
        data["admin"].id
    )

    after = service.now()

    assert second.status == "READY"

    assert (
        before + timedelta(days=7)
        <= second.expires_at
        <= after + timedelta(days=7)
    )


def test_process_queue_expires_ready_reservation(
    service, data, ready_reservation, copy
):

    make_expired(
        service,
        ready_reservation
    )

    service.process_queue(
        data["admin"].id,
        data["book"].id
    )

    assert ready_reservation.status == "EXPIRED"
    assert copy.status == "AVAILABLE"


def test_expire_multiple_reservations_same_book(
    service, copy_service, data
):

    copies = []

    for number in range(1, 4):

        copies.append(
            copy_service.create_copy(
                data["admin"].id,
                data["book"].id,
                f"INV-{number:03d}"
            )
        )

    reservations = []

    for reader in data["readers"][:3]:

        reservations.append(
            service.create_reservation(
                data["admin"].id,
                reader.id,
                data["book"].id
            )
        )

    make_expired(service, reservations[0])
    make_expired(service, reservations[1])

    result = service.expire_reservations(
        data["admin"].id
    )

    assert len(result) == 2

    assert reservations[0].status == "EXPIRED"
    assert reservations[1].status == "EXPIRED"
    assert reservations[2].status == "READY"

    assert count_reserved_copies(
        data["book"].id
    ) == 1

    assert count_ready_reservations(
        data["book"].id
    ) == 1

    assert Copy.query.filter_by(
        book_id=data["book"].id,
        status="AVAILABLE"
    ).count() == 2


def test_expire_reservations_for_multiple_books(
    service, copy_service, data
):

    reservations = []
    copies = []

    for number, book in enumerate(
        data["books"][:2],
        start=1
    ):

        copies.append(
            copy_service.create_copy(
                data["admin"].id,
                book.id,
                f"INV-{number:03d}"
            )
        )

        reservations.append(
            service.create_reservation(
                data["admin"].id,
                data["reader"].id,
                book.id
            )
        )

    for reservation in reservations:

        make_expired(
            service,
            reservation
        )

    result = service.expire_reservations(
        data["admin"].id
    )

    assert len(result) == 2

    assert all(
        reservation.status == "EXPIRED"
        for reservation in reservations
    )

    assert all(
        copy.status == "AVAILABLE"
        for copy in copies
    )


# ==========================================
# EXPIRATION LIMIT TESTS
# ==========================================

def test_expiration_frees_reservation_limit(
    service, data, ready_reservation
):

    service.setting_service.update(
        "MAX_ACTIVE_RESERVATIONS",
        1
    )

    make_expired(
        service,
        ready_reservation
    )

    service.expire_reservations(
        data["admin"].id
    )

    result = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["other_book"].id
    )

    assert ready_reservation.status == "EXPIRED"
    assert result.status == "WAITING"


def test_can_reserve_same_book_after_expiration(
    service, data, ready_reservation, copy
):

    make_expired(
        service,
        ready_reservation
    )

    service.expire_reservations(
        data["admin"].id
    )

    result = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    assert ready_reservation.status == "EXPIRED"
    assert result.id != ready_reservation.id
    assert result.status == "READY"
    assert copy.status == "RESERVED"


def test_expired_ready_reservation_has_no_position(
    service, data, ready_reservation
):

    make_expired(
        service,
        ready_reservation
    )

    result = service.get_queue_position(
        data["admin"].id,
        ready_reservation.id
    )

    assert result is None
    assert ready_reservation.status == "READY"


# ==========================================
# EXPIRATION IDEMPOTENCY
# ==========================================

def test_expiration_is_idempotent(
    service, data, ready_reservation, copy
):

    make_expired(
        service,
        ready_reservation
    )

    first = service.expire_reservations(
        data["admin"].id
    )

    second = service.expire_reservations(
        data["admin"].id
    )

    assert len(first) == 1
    assert second == []

    assert ready_reservation.status == "EXPIRED"
    assert copy.status == "AVAILABLE"

    assert AuditLog.query.filter_by(
        action="RESERVATION_EXPIRED"
    ).count() == 1


# ==========================================
# EXPIRATION AUDIT TESTS
# ==========================================

def test_expiration_audit(
    service, data, ready_reservation
):

    make_expired(
        service,
        ready_reservation
    )

    service.expire_reservations(
        data["admin"].id
    )

    log = AuditLog.query.filter_by(
        action="RESERVATION_EXPIRED"
    ).one()

    assert log.user_id == data["admin"].id

    assert str(
        ready_reservation.id
    ) in log.description


def test_expiration_and_queue_audit(
    service, data, ready_reservation, copy
):

    second = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["book"].id
    )

    make_expired(
        service,
        ready_reservation
    )

    service.expire_reservations(
        data["admin"].id
    )

    assert second.status == "READY"

    assert AuditLog.query.filter_by(
        action="RESERVATION_EXPIRED"
    ).count() == 1

    assert AuditLog.query.filter_by(
        action="RESERVATION_READY"
    ).count() == 2


# ==========================================
# EXPIRATION TRANSACTION TESTS
# ==========================================

def test_expiration_audit_rollback(
    service, data, ready_reservation,
    copy, monkeypatch
):

    make_expired(
        service,
        ready_reservation
    )

    original_log = service.audit_service.log

    def fail_expiration_audit(
        action, *args, **kwargs
    ):

        if action == "RESERVATION_EXPIRED":

            raise RuntimeError(
                "Simulated expiration audit failure."
            )

        return original_log(
            action, *args, **kwargs
        )

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_expiration_audit
    )

    with pytest.raises(RuntimeError):

        service.expire_reservations(
            data["admin"].id
        )

    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"

    assert AuditLog.query.filter_by(
        action="RESERVATION_EXPIRED"
    ).count() == 0


def test_expiration_queue_rollback(
    service, data, ready_reservation,
    copy, monkeypatch
):

    second = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["book"].id
    )

    make_expired(
        service,
        ready_reservation
    )

    original_process = service._process_queue

    def fail_queue(*args, **kwargs):

        original_process(*args, **kwargs)

        raise RuntimeError(
            "Simulated expiration queue failure."
        )

    monkeypatch.setattr(
        service,
        "_process_queue",
        fail_queue
    )

    with pytest.raises(RuntimeError):

        service.expire_reservations(
            data["admin"].id
        )

    assert ready_reservation.status == "READY"
    assert second.status == "WAITING"
    assert second.expires_at is None
    assert copy.status == "RESERVED"

    assert count_reserved_copies(
        data["book"].id
    ) == 1

    assert count_ready_reservations(
        data["book"].id
    ) == 1

    assert AuditLog.query.filter_by(
        action="RESERVATION_EXPIRED"
    ).count() == 0

    assert AuditLog.query.filter_by(
        action="RESERVATION_READY"
    ).count() == 1

# ==========================================
# FULFILLMENT TESTS
# ==========================================

def test_fulfill_reservation_by_admin(
    service, data, ready_reservation, copy
):

    loan = service.fulfill_reservation(
        data["admin"].id,
        ready_reservation.id
    )

    assert loan.id is not None
    assert loan.status == "ACTIVE"
    assert loan.copy_id == copy.id

    assert loan.reader_id == (
        data["reader"].id
    )

    assert ready_reservation.status == "FULFILLED"
    assert copy.status == "LOANED"

    assert Loan.query.count() == 1


def test_fulfill_reservation_by_librarian(
    service, data, ready_reservation, copy
):

    loan = service.fulfill_reservation(
        data["librarian"].id,
        ready_reservation.id
    )

    assert loan.status == "ACTIVE"
    assert ready_reservation.status == "FULFILLED"
    assert copy.status == "LOANED"


def test_fulfill_with_selected_copy(
    service, data, ready_reservation, copy
):

    loan = service.fulfill_reservation(
        data["admin"].id,
        ready_reservation.id,
        copy.id
    )

    assert loan.copy_id == copy.id
    assert copy.status == "LOANED"
    assert ready_reservation.status == "FULFILLED"


def test_fulfillment_selects_reserved_copy(
    service, copy_service, data
):

    first = copy_service.create_copy(
        data["admin"].id,
        data["book"].id,
        "INV-001"
    )

    second = copy_service.create_copy(
        data["admin"].id,
        data["book"].id,
        "INV-002"
    )

    reservation = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    loan = service.fulfill_reservation(
        data["admin"].id,
        reservation.id
    )

    assert loan.copy_id == first.id
    assert first.status == "LOANED"
    assert second.status == "AVAILABLE"


@pytest.mark.parametrize(
    "loan_days",
    [30, 14]
)
def test_fulfillment_loan_period(
    service, data, ready_reservation, loan_days
):

    if loan_days != 30:

        service.setting_service.update(
            "LOAN_PERIOD_DAYS",
            loan_days
        )

    before = service.now()

    loan = service.fulfill_reservation(
        data["admin"].id,
        ready_reservation.id
    )

    after = service.now()

    assert (
        before
        <= loan.borrowed_at
        <= after
    )

    assert loan.due_date == (
        loan.borrowed_at
        + timedelta(days=loan_days)
    )

    assert loan.returned_at is None


# ==========================================
# FULFILLMENT AUTHORIZATION
# ==========================================

def test_reader_cannot_fulfill_own_reservation(
    service, data, ready_reservation, copy
):

    with pytest.raises(AuthorizationError):

        service.fulfill_reservation(
            data["user"].id,
            ready_reservation.id
        )

    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"
    assert Loan.query.count() == 0


def test_unauthenticated_fulfillment(
    service, ready_reservation
):

    with pytest.raises(AuthenticationError):

        service.fulfill_reservation(
            None,
            ready_reservation.id
        )

    assert ready_reservation.status == "READY"
    assert Loan.query.count() == 0


def test_inactive_admin_cannot_fulfill(
    service, data, ready_reservation
):

    data["admin"].is_active = False
    db.session.commit()

    with pytest.raises(InactiveAccountError):

        service.fulfill_reservation(
            data["admin"].id,
            ready_reservation.id
        )

    assert ready_reservation.status == "READY"
    assert Loan.query.count() == 0


def test_cannot_fulfill_for_inactive_reader(
    service, data, ready_reservation, copy
):

    data["user"].is_active = False
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.fulfill_reservation(
            data["admin"].id,
            ready_reservation.id
        )

    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"
    assert Loan.query.count() == 0


# ==========================================
# FULFILLMENT STATUS VALIDATION
# ==========================================

def test_cannot_fulfill_waiting_reservation(
    service, data, waiting_reservation
):

    with pytest.raises(BusinessRuleError):

        service.fulfill_reservation(
            data["admin"].id,
            waiting_reservation.id
        )

    assert waiting_reservation.status == "WAITING"
    assert Loan.query.count() == 0


@pytest.mark.parametrize(
    "status",
    ["FULFILLED", "CANCELLED", "EXPIRED"]
)
def test_cannot_fulfill_inactive_reservation(
    service, data, status
):

    reservation = Reservation(
        reader_id=data["reader"].id,
        book_id=data["book"].id,
        reserved_at=service.now(),
        status=status
    )

    db.session.add(reservation)
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.fulfill_reservation(
            data["admin"].id,
            reservation.id
        )

    assert reservation.status == status
    assert Loan.query.count() == 0


def test_cannot_fulfill_expired_ready_reservation(
    service, data, ready_reservation, copy
):

    make_expired(
        service,
        ready_reservation
    )

    with pytest.raises(BusinessRuleError):

        service.fulfill_reservation(
            data["admin"].id,
            ready_reservation.id
        )

    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"
    assert Loan.query.count() == 0


def test_cannot_fulfill_without_expiry_date(
    service, data, ready_reservation, copy
):

    ready_reservation.expires_at = None
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.fulfill_reservation(
            data["admin"].id,
            ready_reservation.id
        )

    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"
    assert Loan.query.count() == 0


def test_cannot_fulfill_twice(
    service, data, ready_reservation, copy
):

    first = service.fulfill_reservation(
        data["admin"].id,
        ready_reservation.id
    )

    with pytest.raises(BusinessRuleError):

        service.fulfill_reservation(
            data["admin"].id,
            ready_reservation.id
        )

    assert first.status == "ACTIVE"
    assert ready_reservation.status == "FULFILLED"
    assert copy.status == "LOANED"
    assert Loan.query.count() == 1


def test_cannot_fulfill_archived_book(
    service, data, ready_reservation, copy
):

    data["book"].is_archived = True
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.fulfill_reservation(
            data["admin"].id,
            ready_reservation.id
        )

    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"
    assert Loan.query.count() == 0


# ==========================================
# FULFILLMENT IDENTIFIER VALIDATION
# ==========================================

@pytest.mark.parametrize(
    "invalid_id",
    [None, 0, -1, True, "1", 1.5]
)
def test_fulfill_invalid_reservation_id(
    service, data, invalid_id
):

    with pytest.raises(ValidationError):

        service.fulfill_reservation(
            data["admin"].id,
            invalid_id
        )

    assert Loan.query.count() == 0


def test_fulfill_nonexistent_reservation(
    service, data
):

    with pytest.raises(NotFoundError):

        service.fulfill_reservation(
            data["admin"].id,
            99999
        )

    assert Loan.query.count() == 0


@pytest.mark.parametrize(
    "invalid_id",
    [0, -1, True, "1", 1.5]
)
def test_fulfill_invalid_copy_id(
    service, data, ready_reservation,
    copy, invalid_id
):

    with pytest.raises(ValidationError):

        service.fulfill_reservation(
            data["admin"].id,
            ready_reservation.id,
            invalid_id
        )

    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"
    assert Loan.query.count() == 0


def test_fulfill_nonexistent_copy(
    service, data, ready_reservation, copy
):

    with pytest.raises(BusinessRuleError):

        service.fulfill_reservation(
            data["admin"].id,
            ready_reservation.id,
            99999
        )

    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"
    assert Loan.query.count() == 0


# ==========================================
# FULFILLMENT COPY PROTECTION
# ==========================================

def test_cannot_fulfill_with_available_copy(
    service, copy_service, data,
    ready_reservation, copy
):

    second = copy_service.create_copy(
        data["admin"].id,
        data["book"].id,
        "INV-002"
    )

    with pytest.raises(BusinessRuleError):

        service.fulfill_reservation(
            data["admin"].id,
            ready_reservation.id,
            second.id
        )

    assert second.status == "AVAILABLE"
    assert copy.status == "RESERVED"
    assert ready_reservation.status == "READY"
    assert Loan.query.count() == 0


def test_cannot_fulfill_with_other_book_copy(
    service, copy_service, data,
    ready_reservation, copy
):

    other_copy = copy_service.create_copy(
        data["admin"].id,
        data["other_book"].id,
        "INV-002"
    )

    other_reservation = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["other_book"].id
    )

    with pytest.raises(BusinessRuleError):

        service.fulfill_reservation(
            data["admin"].id,
            ready_reservation.id,
            other_copy.id
        )

    assert other_copy.status == "RESERVED"
    assert copy.status == "RESERVED"
    assert ready_reservation.status == "READY"
    assert other_reservation.status == "READY"
    assert Loan.query.count() == 0


# ==========================================
# FULFILLMENT LOAN LIMIT TESTS
# ==========================================

def test_fulfillment_respects_loan_limit(
    service, loan_service, copy_service,
    data, ready_reservation, copy
):

    service.setting_service.update(
        "MAX_ACTIVE_LOANS",
        1
    )

    other_copy = copy_service.create_copy(
        data["admin"].id,
        data["other_book"].id,
        "INV-002"
    )

    existing_loan = loan_service.borrow_book(
        data["admin"].id,
        data["reader"].id,
        other_copy.id
    )

    with pytest.raises(LoanLimitExceededError):

        service.fulfill_reservation(
            data["admin"].id,
            ready_reservation.id
        )

    assert existing_loan.status == "ACTIVE"
    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"
    assert Loan.query.count() == 1


def test_fulfillment_after_freeing_loan_limit(
    service, loan_service, copy_service,
    data, ready_reservation, copy
):

    service.setting_service.update(
        "MAX_ACTIVE_LOANS",
        1
    )

    other_copy = copy_service.create_copy(
        data["admin"].id,
        data["other_book"].id,
        "INV-002"
    )

    existing = loan_service.borrow_book(
        data["admin"].id,
        data["reader"].id,
        other_copy.id
    )

    loan_service.return_book(
        data["admin"].id,
        existing.id
    )

    loan = service.fulfill_reservation(
        data["admin"].id,
        ready_reservation.id
    )

    assert existing.status == "RETURNED"
    assert loan.status == "ACTIVE"
    assert ready_reservation.status == "FULFILLED"
    assert copy.status == "LOANED"


def test_fulfillment_frees_reservation_limit(
    service, data, ready_reservation
):

    service.setting_service.update(
        "MAX_ACTIVE_RESERVATIONS",
        1
    )

    service.fulfill_reservation(
        data["admin"].id,
        ready_reservation.id
    )

    second = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["other_book"].id
    )

    assert ready_reservation.status == "FULFILLED"
    assert second.status == "WAITING"


# ==========================================
# FULFILLMENT QUEUE INTEGRATION
# ==========================================

def test_fulfillment_preserves_waiting_queue(
    service, data, ready_reservation, copy
):

    second = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["book"].id
    )

    service.fulfill_reservation(
        data["admin"].id,
        ready_reservation.id
    )

    assert ready_reservation.status == "FULFILLED"
    assert second.status == "WAITING"
    assert second.expires_at is None
    assert copy.status == "LOANED"

    assert count_reserved_copies(
        data["book"].id
    ) == 0

    assert count_ready_reservations(
        data["book"].id
    ) == 0


def test_return_after_fulfillment_processes_queue(
    service, loan_service, data,
    ready_reservation, copy
):

    second = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["book"].id
    )

    loan = service.fulfill_reservation(
        data["admin"].id,
        ready_reservation.id
    )

    loan_service.return_book(
        data["admin"].id,
        loan.id
    )

    assert loan.status == "RETURNED"
    assert ready_reservation.status == "FULFILLED"
    assert second.status == "READY"
    assert second.expires_at is not None
    assert copy.status == "RESERVED"


# ==========================================
# FULFILLMENT AUDIT TESTS
# ==========================================

def test_fulfillment_creates_audit_entries(
    service, data, ready_reservation
):

    loan = service.fulfill_reservation(
        data["admin"].id,
        ready_reservation.id
    )

    loan_log = AuditLog.query.filter_by(
        action="LOAN_CREATED"
    ).one()

    reservation_log = AuditLog.query.filter_by(
        action="RESERVATION_FULFILLED"
    ).one()

    assert loan_log.user_id == data["admin"].id

    assert reservation_log.user_id == (
        data["admin"].id
    )

    assert str(loan.id) in reservation_log.description

    assert str(
        ready_reservation.id
    ) in reservation_log.description


# ==========================================
# FULFILLMENT TRANSACTION TESTS
# ==========================================

def test_fulfillment_audit_rollback(
    service, data, ready_reservation,
    copy, monkeypatch
):

    original_log = service.audit_service.log

    def fail_fulfillment_audit(
        action, *args, **kwargs
    ):

        if action == "RESERVATION_FULFILLED":

            raise RuntimeError(
                "Simulated fulfillment audit failure."
            )

        return original_log(
            action, *args, **kwargs
        )

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_fulfillment_audit
    )

    with pytest.raises(RuntimeError):

        service.fulfill_reservation(
            data["admin"].id,
            ready_reservation.id
        )

    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"
    assert Loan.query.count() == 0

    assert AuditLog.query.filter_by(
        action="LOAN_CREATED"
    ).count() == 0

    assert AuditLog.query.filter_by(
        action="RESERVATION_FULFILLED"
    ).count() == 0


def test_fulfillment_queue_rollback(
    service, data, ready_reservation,
    copy, monkeypatch
):

    second = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["book"].id
    )

    original_process = service._process_queue

    def fail_queue(*args, **kwargs):

        original_process(*args, **kwargs)

        raise RuntimeError(
            "Simulated fulfillment queue failure."
        )

    monkeypatch.setattr(
        service,
        "_process_queue",
        fail_queue
    )

    with pytest.raises(RuntimeError):

        service.fulfill_reservation(
            data["admin"].id,
            ready_reservation.id
        )

    assert ready_reservation.status == "READY"
    assert second.status == "WAITING"
    assert copy.status == "RESERVED"
    assert Loan.query.count() == 0

    assert count_reserved_copies(
        data["book"].id
    ) == 1

    assert count_ready_reservations(
        data["book"].id
    ) == 1

    assert AuditLog.query.filter_by(
        action="LOAN_CREATED"
    ).count() == 0

    assert AuditLog.query.filter_by(
        action="RESERVATION_FULFILLED"
    ).count() == 0


# ==========================================
# READ TEST FIXTURE
# ==========================================

@pytest.fixture
def reservation_history(
    service, data, ready_reservation
):

    waiting = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["books"][1].id
    )

    other = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["book"].id
    )

    history = {
        "READY": ready_reservation,
        "WAITING": waiting,
        "OTHER": other
    }

    for index, status in enumerate(
        ["CANCELLED", "FULFILLED", "EXPIRED"],
        start=2
    ):

        reservation = Reservation(
            book_id=data["books"][index].id,
            reader_id=data["reader"].id,
            status=status,
            reserved_at=(
                service.now() - timedelta(days=10)
            ),
            expires_at=(
                service.now() - timedelta(days=7)
            )
        )

        db.session.add(reservation)

        history[status] = reservation

    db.session.commit()

    return history


# ==========================================
# GET BY ID TESTS
# ==========================================

@pytest.mark.parametrize(
    "role",
    ["admin", "librarian", "user"]
)
def test_read_reservation_by_id(
    service, data, waiting_reservation, role
):

    result = service.get_by_id(
        data[role].id,
        waiting_reservation.id
    )

    assert result.id == waiting_reservation.id
    assert result.status == "WAITING"

    assert result.reader_id == (
        data["reader"].id
    )


# ==========================================
# GET ALL TESTS
# ==========================================

@pytest.mark.parametrize(
    "role",
    ["admin", "librarian"]
)
def test_staff_can_read_all_reservations(
    service, data, reservation_history, role
):

    result = service.get_all(
        data[role].id
    )

    expected_ids = {
        reservation.id
        for reservation in reservation_history.values()
    }

    assert len(result) == 6

    assert {
        reservation.id
        for reservation in result
    } == expected_ids


# ==========================================
# GET BY READER TESTS
# ==========================================

@pytest.mark.parametrize(
    "role",
    ["admin", "user"]
)
def test_read_reservation_history_by_reader(
    service, data, reservation_history, role
):

    result = service.get_by_reader(
        data[role].id,
        data["reader"].id
    )

    assert len(result) == 5

    assert all(
        item.reader_id == data["reader"].id
        for item in result
    )

    assert {
        item.status
        for item in result
    } == {
        "WAITING",
        "READY",
        "FULFILLED",
        "CANCELLED",
        "EXPIRED"
    }


# ==========================================
# GET BY BOOK TESTS
# ==========================================

def test_read_reservations_by_book(
    service, data, reservation_history
):

    result = service.get_by_book(
        data["admin"].id,
        data["book"].id
    )

    assert len(result) == 2

    assert all(
        item.book_id == data["book"].id
        for item in result
    )

    assert {
        item.id
        for item in result
    } == {
        reservation_history["READY"].id,
        reservation_history["OTHER"].id
    }


# ==========================================
# GET BY STATUS TESTS
# ==========================================

@pytest.mark.parametrize(
    "status",
    [
        "WAITING",
        "READY",
        "FULFILLED",
        "CANCELLED",
        "EXPIRED"
    ]
)
def test_filter_reservations_by_status(
    service, data, reservation_history, status
):

    result = service.get_by_status(
        data["admin"].id,
        status
    )

    expected_count = (
        2 if status == "WAITING" else 1
    )

    assert len(result) == expected_count

    assert all(
        item.status == status
        for item in result
    )


def test_reservation_status_filter_normalization(
    service, data, reservation_history
):

    result = service.get_by_status(
        data["admin"].id,
        "  ready  "
    )

    assert len(result) == 1

    assert result[0].id == (
        reservation_history["READY"].id
    )


# ==========================================
# WAITING QUEUE READ TESTS
# ==========================================

def test_read_waiting_queue_in_fifo_order(
    service, data
):

    now = service.now()

    newer = create_waiting_reservation(
        service,
        data["book"],
        data["readers"][1],
        now - timedelta(hours=1)
    )

    older = create_waiting_reservation(
        service,
        data["book"],
        data["readers"][0],
        now - timedelta(hours=2)
    )

    newest = create_waiting_reservation(
        service,
        data["book"],
        data["readers"][2],
        now
    )

    result = service.get_waiting_by_book(
        data["admin"].id,
        data["book"].id
    )

    assert [
        item.id for item in result
    ] == [
        older.id,
        newer.id,
        newest.id
    ]


# ==========================================
# ACTIVE RESERVATION READ TESTS
# ==========================================

@pytest.mark.parametrize(
    "role",
    ["admin", "user"]
)
def test_read_active_reservations(
    service, data, reservation_history, role
):

    result = service.get_active_by_reader(
        data[role].id,
        data["reader"].id
    )

    assert len(result) == 2

    assert {
        item.status
        for item in result
    } == {
        "WAITING",
        "READY"
    }

    assert all(
        item.reader_id == data["reader"].id
        for item in result
    )


# ==========================================
# OWN RESERVATION HISTORY TESTS
# ==========================================

def test_read_own_reservation_history(
    service, data, reservation_history
):

    result = service.get_own_reservations(
        data["user"].id
    )

    assert len(result) == 5

    assert all(
        item.reader_id == data["reader"].id
        for item in result
    )

    assert reservation_history["OTHER"].id not in {
        item.id
        for item in result
    }


def test_read_own_active_reservations(
    service, data, reservation_history
):

    result = service.get_own_active_reservations(
        data["user"].id
    )

    assert len(result) == 2

    assert {
        item.status
        for item in result
    } == {
        "WAITING",
        "READY"
    }

    assert all(
        item.reader_id == data["reader"].id
        for item in result
    )


# ==========================================
# EXPIRED RESERVATION READ TESTS
# ==========================================

def test_read_expired_ready_reservations(
    service, data, ready_reservation, copy
):

    make_expired(
        service,
        ready_reservation
    )

    result = service.get_expired_reservations(
        data["admin"].id
    )

    assert len(result) == 1
    assert result[0].id == ready_reservation.id

    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"


# ==========================================
# RESERVATION COUNT TESTS
# ==========================================

@pytest.mark.parametrize(
    "role",
    ["admin", "user"]
)
def test_count_active_reservations(
    service, data, reservation_history, role
):

    result = service.count_active_by_reader(
        data[role].id,
        data["reader"].id
    )

    assert result == 2


def test_count_all_reservations(
    service, data, reservation_history
):

    result = service.count(
        data["admin"].id
    )

    assert result == 6


# ==========================================
# EMPTY RESULT TESTS
# ==========================================

def test_read_empty_reservation_collection(
    service, data
):

    actor_id = data["admin"].id
    reader_id = data["reader"].id
    book_id = data["book"].id
    user_id = data["user"].id

    assert service.get_all(actor_id) == []

    assert service.get_by_reader(
        actor_id, reader_id
    ) == []

    assert service.get_by_book(
        actor_id, book_id
    ) == []

    assert service.get_by_status(
        actor_id, "WAITING"
    ) == []

    assert service.get_waiting_by_book(
        actor_id, book_id
    ) == []

    assert service.get_active_by_reader(
        actor_id, reader_id
    ) == []

    assert service.get_own_reservations(
        user_id
    ) == []

    assert service.get_own_active_reservations(
        user_id
    ) == []

    assert service.get_expired_reservations(
        actor_id
    ) == []

    assert service.count_active_by_reader(
        actor_id, reader_id
    ) == 0

    assert service.count(actor_id) == 0


# ==========================================
# READ AUTHORIZATION TESTS
# ==========================================

@pytest.mark.parametrize(
    "method_name",
    [
        "get_by_book",
        "get_waiting_by_book",
        "get_by_status",
        "get_expired_reservations",
        "count"
    ]
)
def test_reader_cannot_use_staff_read_methods(
    service, data, reservation_history, method_name
):

    method = getattr(
        service,
        method_name
    )

    arguments = {
        "get_by_book": [
            data["book"].id
        ],
        "get_waiting_by_book": [
            data["book"].id
        ],
        "get_by_status": [
            "WAITING"
        ],
        "get_expired_reservations": [],
        "count": []
    }

    with pytest.raises(AuthorizationError):

        method(
            data["user"].id,
            *arguments[method_name]
        )


def test_reader_cannot_detect_missing_reservation(
    service, data
):

    with pytest.raises(AuthorizationError):

        service.get_by_id(
            data["user"].id,
            99999
        )


def test_reader_cannot_read_other_active_reservations(
    service, data, reservation_history
):

    with pytest.raises(AuthorizationError):

        service.get_active_by_reader(
            data["user"].id,
            data["other_reader"].id
        )


def test_reader_cannot_count_other_reservations(
    service, data, reservation_history
):

    with pytest.raises(AuthorizationError):

        service.count_active_by_reader(
            data["user"].id,
            data["other_reader"].id
        )


def test_reader_can_read_own_queue_position(
    service, data, waiting_reservation
):

    result = service.get_queue_position(
        data["user"].id,
        waiting_reservation.id
    )

    assert result == 1


# ==========================================
# READ SIDE EFFECT TESTS
# ==========================================

def test_read_operations_do_not_modify_data(
    service, data, reservation_history
):

    before = {
        item.id: (
            item.status,
            item.reserved_at,
            item.expires_at
        )
        for item in Reservation.query.all()
    }

    audit_count = AuditLog.query.count()

    actor_id = data["admin"].id
    reader_id = data["reader"].id
    book_id = data["book"].id

    service.get_all(actor_id)

    service.get_by_reader(
        actor_id,
        reader_id
    )

    service.get_by_book(
        actor_id,
        book_id
    )

    service.get_by_status(
        actor_id,
        "READY"
    )

    service.get_active_by_reader(
        actor_id,
        reader_id
    )

    service.get_expired_reservations(
        actor_id
    )

    service.count(actor_id)

    after = {
        item.id: (
            item.status,
            item.reserved_at,
            item.expires_at
        )
        for item in Reservation.query.all()
    }

    assert before == after

    assert AuditLog.query.count() == audit_count


# ==========================================
# DATA CONSISTENCY TESTS
# ==========================================

@pytest.mark.parametrize(
    "operation",
    ["process", "cancel", "fulfill"]
)
def test_ready_reservation_without_reserved_copy(
    service, data, ready_reservation,
    copy, operation
):

    copy.status = "AVAILABLE"
    db.session.commit()

    actor_id = data["admin"].id

    with pytest.raises(BusinessRuleError):

        if operation == "process":

            service.process_queue(
                actor_id,
                data["book"].id
            )

        elif operation == "cancel":

            service.cancel_reservation(
                actor_id,
                ready_reservation.id
            )

        else:

            service.fulfill_reservation(
                actor_id,
                ready_reservation.id
            )

    assert ready_reservation.status == "READY"
    assert copy.status == "AVAILABLE"
    assert Loan.query.count() == 0


def test_reserved_copy_without_ready_reservation(
    service, data, copy
):

    copy.status = "RESERVED"
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.process_queue(
            data["admin"].id,
            data["book"].id
        )

    assert copy.status == "RESERVED"
    assert Reservation.query.count() == 0


def test_reserved_copy_with_active_loan(
    service, data, ready_reservation, copy
):

    loan = Loan(
        copy_id=copy.id,
        reader_id=data["other_reader"].id,
        borrowed_at=service.now(),
        due_date=(
            service.now() + timedelta(days=30)
        ),
        status="ACTIVE"
    )

    db.session.add(loan)
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.process_queue(
            data["admin"].id,
            data["book"].id
        )

    assert copy.status == "RESERVED"
    assert ready_reservation.status == "READY"
    assert loan.status == "ACTIVE"


def test_available_copy_with_active_loan(
    service, data, copy
):

    loan = Loan(
        copy_id=copy.id,
        reader_id=data["other_reader"].id,
        borrowed_at=service.now(),
        due_date=(
            service.now() + timedelta(days=30)
        ),
        status="ACTIVE"
    )

    db.session.add(loan)
    db.session.commit()

    reservation = create_waiting_reservation(
        service,
        data["book"],
        data["reader"]
    )

    with pytest.raises(BusinessRuleError):

        service.process_queue(
            data["admin"].id,
            data["book"].id
        )

    assert reservation.status == "WAITING"
    assert reservation.expires_at is None
    assert copy.status == "AVAILABLE"
    assert loan.status == "ACTIVE"


def test_queue_rejects_ready_without_expiry(
    service, data, ready_reservation, copy
):

    ready_reservation.expires_at = None
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.process_queue(
            data["admin"].id,
            data["book"].id
        )

    assert ready_reservation.status == "READY"
    assert ready_reservation.expires_at is None
    assert copy.status == "RESERVED"


def test_creation_rejects_inconsistent_pool(
    service, data, copy
):

    copy.status = "RESERVED"
    db.session.commit()

    audit_count = AuditLog.query.count()

    with pytest.raises(BusinessRuleError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            data["book"].id
        )

    assert Reservation.query.count() == 0
    assert copy.status == "RESERVED"

    assert AuditLog.query.count() == (
        audit_count
    )


# ==========================================
# MULTIPLE RESERVED COPIES
# ==========================================

def test_fulfillment_from_shared_reserved_pool(
    service, copy_service, data
):

    first_copy = copy_service.create_copy(
        data["admin"].id,
        data["book"].id,
        "INV-001"
    )

    second_copy = copy_service.create_copy(
        data["admin"].id,
        data["book"].id,
        "INV-002"
    )

    first_reservation = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    second_reservation = service.create_reservation(
        data["admin"].id,
        data["other_reader"].id,
        data["book"].id
    )

    assert first_reservation.status == "READY"
    assert second_reservation.status == "READY"

    assert count_reserved_copies(
        data["book"].id
    ) == 2

    loan = service.fulfill_reservation(
        data["admin"].id,
        first_reservation.id,
        second_copy.id
    )

    assert loan.copy_id == second_copy.id
    assert first_reservation.status == "FULFILLED"
    assert second_reservation.status == "READY"

    assert first_copy.status == "RESERVED"
    assert second_copy.status == "LOANED"

    assert count_reserved_copies(
        data["book"].id
    ) == 1

    assert count_ready_reservations(
        data["book"].id
    ) == 1


# ==========================================
# RESERVATION LIFECYCLE CONSISTENCY
# ==========================================

def test_consistency_through_full_lifecycle(
    service, copy_service, loan_service, data
):

    actor_id = data["admin"].id
    book_id = data["book"].id

    first = service.create_reservation(
        actor_id,
        data["readers"][0].id,
        book_id
    )

    second = service.create_reservation(
        actor_id,
        data["readers"][1].id,
        book_id
    )

    third = service.create_reservation(
        actor_id,
        data["readers"][2].id,
        book_id
    )

    assert first.status == "WAITING"
    assert second.status == "WAITING"
    assert third.status == "WAITING"

    assert count_reserved_copies(book_id) == 0
    assert count_ready_reservations(book_id) == 0

    copy = copy_service.create_copy(
        actor_id,
        book_id,
        "INV-001"
    )

    assert first.status == "READY"
    assert copy.status == "RESERVED"

    assert count_reserved_copies(book_id) == 1
    assert count_ready_reservations(book_id) == 1

    service.cancel_reservation(
        actor_id,
        first.id
    )

    assert first.status == "CANCELLED"
    assert second.status == "READY"
    assert third.status == "WAITING"

    assert count_reserved_copies(book_id) == 1
    assert count_ready_reservations(book_id) == 1

    loan = service.fulfill_reservation(
        actor_id,
        second.id
    )

    assert second.status == "FULFILLED"
    assert copy.status == "LOANED"
    assert loan.status == "ACTIVE"

    assert count_reserved_copies(book_id) == 0
    assert count_ready_reservations(book_id) == 0

    loan_service.return_book(
        actor_id,
        loan.id
    )

    assert loan.status == "RETURNED"
    assert third.status == "READY"
    assert copy.status == "RESERVED"

    assert count_reserved_copies(book_id) == 1
    assert count_ready_reservations(book_id) == 1

    make_expired(service, third)

    service.expire_reservations(actor_id)

    assert third.status == "EXPIRED"
    assert copy.status == "AVAILABLE"

    assert count_reserved_copies(book_id) == 0
    assert count_ready_reservations(book_id) == 0

    assert Reservation.query.count() == 3
    assert Loan.query.count() == 1


# ==========================================
# BOOK ISOLATION TESTS
# ==========================================

def test_inconsistent_pool_does_not_affect_other_book(
    service, copy_service, data, copy
):

    copy.status = "RESERVED"
    db.session.commit()

    other_copy = copy_service.create_copy(
        data["admin"].id,
        data["other_book"].id,
        "INV-002"
    )

    reservation = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["other_book"].id
    )

    assert reservation.status == "READY"
    assert other_copy.status == "RESERVED"

    assert copy.status == "RESERVED"

    assert count_reserved_copies(
        data["other_book"].id
    ) == 1

    assert count_ready_reservations(
        data["other_book"].id
    ) == 1


# ==========================================
# EXPIRATION CONSISTENCY TESTS
# ==========================================

def test_expiration_rejects_inconsistent_pool(
    service, data, ready_reservation, copy
):

    make_expired(
        service,
        ready_reservation
    )

    copy.status = "AVAILABLE"
    db.session.commit()

    audit_count = AuditLog.query.count()

    with pytest.raises(BusinessRuleError):

        service.expire_reservations(
            data["admin"].id
        )

    assert ready_reservation.status == "READY"
    assert copy.status == "AVAILABLE"

    assert AuditLog.query.count() == (
        audit_count
    )


# ==========================================
# LOAN CONSISTENCY TESTS
# ==========================================

def test_fulfillment_rejects_existing_book_loan(
    service, copy_service, data,
    ready_reservation, copy
):

    second_copy = copy_service.create_copy(
        data["admin"].id,
        data["book"].id,
        "INV-002"
    )

    second_copy.status = "LOANED"

    existing_loan = Loan(
        copy_id=second_copy.id,
        reader_id=data["reader"].id,
        borrowed_at=service.now(),
        due_date=(
            service.now() + timedelta(days=30)
        ),
        status="ACTIVE"
    )

    db.session.add(existing_loan)
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.fulfill_reservation(
            data["admin"].id,
            ready_reservation.id
        )

    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"
    assert second_copy.status == "LOANED"
    assert existing_loan.status == "ACTIVE"

    assert Loan.query.count() == 1



# ==========================================
# RESERVATION AUDIT TESTS
# ==========================================

@pytest.mark.parametrize(
    "role",
    ["admin", "librarian", "user"]
)
def test_reservation_creation_audit_actor(
    service, data, role
):

    reservation = service.create_reservation(
        data[role].id,
        data["reader"].id,
        data["book"].id
    )

    log = AuditLog.query.filter_by(
        action="RESERVATION_CREATED"
    ).one()

    assert log.user_id == data[role].id
    assert log.created_at is not None

    assert (
        f"Reservation ID: {reservation.id}"
        in log.description
    )

    assert (
        f"Reader ID: {data['reader'].id}"
        in log.description
    )

    assert (
        f"Book ID: {data['book'].id}"
        in log.description
    )


def test_reservation_ready_audit_details(
    service, data, ready_reservation
):

    log = AuditLog.query.filter_by(
        action="RESERVATION_READY"
    ).one()

    assert log.user_id == data["admin"].id
    assert log.created_at is not None

    assert (
        f"Reservation ID: {ready_reservation.id}"
        in log.description
    )

    assert (
        f"Book ID: {data['book'].id}"
        in log.description
    )


def test_waiting_reservation_creates_only_creation_audit(
    service, data, waiting_reservation
):

    assert AuditLog.query.filter_by(
        action="RESERVATION_CREATED"
    ).count() == 1

    assert AuditLog.query.filter_by(
        action="RESERVATION_READY"
    ).count() == 0

    assert waiting_reservation.status == "WAITING"


def test_unauthorized_creation_has_no_success_audit(
    service, data
):

    before = AuditLog.query.count()

    with pytest.raises(AuthorizationError):

        service.create_reservation(
            data["user"].id,
            data["other_reader"].id,
            data["book"].id
        )

    assert Reservation.query.count() == 0
    assert AuditLog.query.count() == before


def test_duplicate_creation_has_no_additional_audit(
    service, data, ready_reservation, copy
):

    before = AuditLog.query.count()

    with pytest.raises(ReservationAlreadyExistsError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            data["book"].id
        )

    assert Reservation.query.count() == 1
    assert AuditLog.query.count() == before
    assert ready_reservation.status == "READY"
    assert copy.status == "RESERVED"


# ==========================================
# CREATION TRANSACTION TESTS
# ==========================================

def test_creation_audit_failure_rollback(
    service, data, copy, monkeypatch
):

    before = AuditLog.query.count()

    original_log = service.audit_service.log

    def fail_creation_audit(
        action, *args, **kwargs
    ):

        original_log(
            action, *args, **kwargs
        )

        if action == "RESERVATION_CREATED":

            raise RuntimeError(
                "Simulated creation audit failure."
            )

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_creation_audit
    )

    with pytest.raises(RuntimeError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            data["book"].id
        )

    assert Reservation.query.count() == 0
    assert copy.status == "AVAILABLE"
    assert AuditLog.query.count() == before

    assert count_reserved_copies(
        data["book"].id
    ) == 0


def test_creation_ready_audit_failure_rollback(
    service, data, copy, monkeypatch
):

    before = AuditLog.query.count()

    original_log = service.audit_service.log

    def fail_ready_audit(
        action, *args, **kwargs
    ):

        original_log(
            action, *args, **kwargs
        )

        if action == "RESERVATION_READY":

            raise RuntimeError(
                "Simulated ready audit failure."
            )

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_ready_audit
    )

    with pytest.raises(RuntimeError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            data["book"].id
        )

    assert Reservation.query.count() == 0
    assert copy.status == "AVAILABLE"
    assert AuditLog.query.count() == before

    assert count_ready_reservations(
        data["book"].id
    ) == 0

    assert count_reserved_copies(
        data["book"].id
    ) == 0


# ==========================================
# QUEUE TRANSACTION TESTS
# ==========================================

def test_multiple_queue_updates_rollback(
    service, copy_service, data, monkeypatch
):

    actor_id = data["admin"].id
    book_id = data["book"].id

    first_copy = copy_service.create_copy(
        actor_id,
        book_id,
        "INV-001"
    )

    second_copy = copy_service.create_copy(
        actor_id,
        book_id,
        "INV-002"
    )

    first = create_waiting_reservation(
        service,
        data["book"],
        data["reader"]
    )

    second = create_waiting_reservation(
        service,
        data["book"],
        data["other_reader"]
    )

    before = AuditLog.query.count()

    original_log = service.audit_service.log

    counter = 0

    def fail_second_ready(
        action, *args, **kwargs
    ):

        nonlocal counter

        result = original_log(
            action, *args, **kwargs
        )

        if action == "RESERVATION_READY":

            counter += 1

            if counter == 2:

                raise RuntimeError(
                    "Simulated second queue update failure."
                )

        return result

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_second_ready
    )

    with pytest.raises(RuntimeError):

        service.process_queue(
            actor_id,
            book_id
        )

    assert counter == 2

    assert first.status == "WAITING"
    assert second.status == "WAITING"

    assert first.expires_at is None
    assert second.expires_at is None

    assert first_copy.status == "AVAILABLE"
    assert second_copy.status == "AVAILABLE"

    assert count_reserved_copies(book_id) == 0
    assert count_ready_reservations(book_id) == 0

    assert AuditLog.query.count() == before


# ==========================================
# DATABASE ERROR TESTS
# ==========================================

def test_reservation_database_error_rollback(
    service, data, copy, monkeypatch
):

    from sqlalchemy.exc import SQLAlchemyError
    from app.exceptions import DatabaseError

    before = AuditLog.query.count()

    original_add = service.repository.add

    def fail_repository_add(reservation):

        original_add(reservation)

        db.session.flush()

        raise SQLAlchemyError(
            "Simulated repository failure."
        )

    monkeypatch.setattr(
        service.repository,
        "add",
        fail_repository_add
    )

    with pytest.raises(DatabaseError):

        service.create_reservation(
            data["admin"].id,
            data["reader"].id,
            data["book"].id
        )

    assert Reservation.query.count() == 0
    assert copy.status == "AVAILABLE"
    assert AuditLog.query.count() == before


def test_reservation_commit_failure_rollback(
    service, data, copy, monkeypatch
):

    from sqlalchemy.exc import SQLAlchemyError
    from app.exceptions import DatabaseError

    before = AuditLog.query.count()

    def fail_commit():

        db.session.flush()

        raise SQLAlchemyError(
            "Simulated commit failure."
        )

    with monkeypatch.context() as patch:

        patch.setattr(
            db.session,
            "commit",
            fail_commit
        )

        with pytest.raises(DatabaseError):

            service.create_reservation(
                data["admin"].id,
                data["reader"].id,
                data["book"].id
            )

    assert Reservation.query.count() == 0
    assert copy.status == "AVAILABLE"
    assert AuditLog.query.count() == before

    assert count_reserved_copies(
        data["book"].id
    ) == 0


# ==========================================
# MULTI-BOOK TRANSACTION TESTS
# ==========================================

def test_multiple_book_expiration_rollback(
    service, copy_service, data, monkeypatch
):

    reservations = []
    copies = []

    actor_id = data["admin"].id

    for number, book in enumerate(
        data["books"][:2],
        start=1
    ):

        copy = copy_service.create_copy(
            actor_id,
            book.id,
            f"INV-{number:03d}"
        )

        copies.append(copy)

        reservation = service.create_reservation(
            actor_id,
            data["reader"].id,
            book.id
        )

        reservations.append(reservation)

    for reservation in reservations:

        make_expired(
            service,
            reservation
        )

    before = AuditLog.query.count()

    original_log = service.audit_service.log

    counter = 0

    def fail_second_expiration(
        action, *args, **kwargs
    ):

        nonlocal counter

        result = original_log(
            action, *args, **kwargs
        )

        if action == "RESERVATION_EXPIRED":

            counter += 1

            if counter == 2:

                raise RuntimeError(
                    "Simulated second expiration failure."
                )

        return result

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_second_expiration
    )

    with pytest.raises(RuntimeError):

        service.expire_reservations(actor_id)

    assert counter == 2

    assert all(
        reservation.status == "READY"
        for reservation in reservations
    )

    assert all(
        copy.status == "RESERVED"
        for copy in copies
    )

    assert AuditLog.query.count() == before

    assert AuditLog.query.filter_by(
        action="RESERVATION_EXPIRED"
    ).count() == 0


# ==========================================
# TRANSACTION RECOVERY TESTS
# ==========================================

def test_reservation_service_recovers_after_rollback(
    service, data, copy, monkeypatch
):

    original_log = service.audit_service.log

    def fail_audit(
        action, *args, **kwargs
    ):

        if action == "RESERVATION_CREATED":

            raise RuntimeError(
                "Simulated temporary audit failure."
            )

        return original_log(
            action, *args, **kwargs
        )

    with monkeypatch.context() as patch:

        patch.setattr(
            service.audit_service,
            "log",
            fail_audit
        )

        with pytest.raises(RuntimeError):

            service.create_reservation(
                data["admin"].id,
                data["reader"].id,
                data["book"].id
            )

    assert Reservation.query.count() == 0
    assert copy.status == "AVAILABLE"

    reservation = service.create_reservation(
        data["admin"].id,
        data["reader"].id,
        data["book"].id
    )

    assert reservation.id is not None
    assert reservation.status == "READY"
    assert copy.status == "RESERVED"

    assert Reservation.query.count() == 1

    assert AuditLog.query.filter_by(
        action="RESERVATION_CREATED"
    ).count() == 1

    assert AuditLog.query.filter_by(
        action="RESERVATION_READY"
    ).count() == 1

# ==========================================
# FINAL COVERAGE TESTS
# ==========================================

def test_release_reserved_copy_without_copies(
    service, data
):

    book_id = data["book"].id

    assert count_reserved_copies(book_id) == 0

    audit_count = AuditLog.query.count()

    with pytest.raises(
        BusinessRuleError,
        match="No reserved copy to release"
    ):

        service._release_reserved_copy(book_id)

    assert count_reserved_copies(book_id) == 0

    assert AuditLog.query.count() == audit_count


def test_internal_queue_ignores_archived_book(
    service, data, copy
):

    book = data["book"]

    reservation = create_waiting_reservation(
        service,
        book,
        data["reader"]
    )

    book.is_archived = True

    db.session.commit()

    audit_count = AuditLog.query.count()

    result = service._process_queue(
        book.id,
        data["admin"].id
    )

    assert result == []

    assert reservation.status == "WAITING"
    assert reservation.expires_at is None
    assert copy.status == "AVAILABLE"

    assert count_reserved_copies(book.id) == 0
    assert count_ready_reservations(book.id) == 0

    assert AuditLog.query.count() == audit_count


def test_queue_position_when_reservation_missing(
    service, data, waiting_reservation,
    monkeypatch
):

    monkeypatch.setattr(
        service.repository,
        "get_waiting_by_book",
        lambda book_id: []
    )

    audit_count = AuditLog.query.count()

    result = service.get_queue_position(
        data["admin"].id,
        waiting_reservation.id
    )

    assert result is None

    assert waiting_reservation.status == "WAITING"

    assert waiting_reservation.expires_at is None

    assert AuditLog.query.count() == audit_count