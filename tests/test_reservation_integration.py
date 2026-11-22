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
    Reservation,
    Fine,
    AuditLog
)

from app.services import (
    AuthService,
    UserService,
    ReaderService,
    CategoryService,
    AuthorService,
    BookService,
    CopyService,
    LoanService,
    ReservationService,
    SettingService,
    AuditService
)

from app.exceptions import (
    ValidationError,
    BusinessRuleError,
    AuthorizationError,
    AuthenticationError,
    NotFoundError,
    CopyUnavailableError,
    LoanLimitExceededError,
    ReservationLimitExceededError,
    ReservationAlreadyExistsError
)


# ==========================================
# INTEGRATION SERVICES FIXTURE
# ==========================================

@pytest.fixture
def services(app):

    return {
        "auth": AuthService(),
        "user": UserService(),
        "reader": ReaderService(),
        "category": CategoryService(),
        "author": AuthorService(),
        "book": BookService(),
        "copy": CopyService(),
        "loan": LoanService(),
        "reservation": ReservationService(),
        "setting": SettingService(),
        "audit": AuditService()
    }


# ==========================================
# INTEGRATION ENVIRONMENT
# ==========================================

@pytest.fixture
def library(services):

    services["setting"].initialize_defaults()

    password = "IntegrationPassword123!"

    # Initial administrator

    admin = User(
        username="integration_admin",
        email="admin@integration.example.com",
        password_hash=services["auth"].hash_password(
            password
        ),
        role="ADMIN",
        is_active=True
    )

    db.session.add(admin)
    db.session.commit()

    # Librarian account

    librarian = services["user"].create_user(
        admin.id,
        "integration_librarian",
        "librarian@integration.example.com",
        password,
        role="LIBRARIAN"
    )

    # Reader accounts

    readers = []

    for number in range(1, 5):

        reader = services["reader"].register_reader(
            librarian.id,
            f"integration_reader{number}",
            f"reader{number}@integration.example.com",
            password,
            "Jan",
            "Kowalski"
        )

        readers.append(reader)

    # Book category

    category = services["category"].create_category(
        librarian.id,
        "Fantasy",
        "Fantasy literature"
    )

    # Author

    author = services["author"].create_author(
        librarian.id,
        "Andrzej",
        "Sapkowski"
    )

    # Library collection

    books = []

    for number in range(1, 4):

        book = services["book"].create_book(
            librarian.id,
            title=f"Integration book {number}",
            publisher="Integration Publisher",
            publication_year=2020,
            category_id=category.id,
            author_ids=[author.id]
        )

        books.append(book)

    return {
        "admin": admin,
        "librarian": librarian,
        "readers": readers,
        "category": category,
        "author": author,
        "books": books,
        "password": password
    }


# ==========================================
# COPY FIXTURE
# ==========================================

@pytest.fixture
def available_copy(services, library):

    return services["copy"].create_copy(
        library["librarian"].id,
        library["books"][0].id,
        "INTEGRATION-001"
    )


# ==========================================
# INTEGRITY HELPERS
# ==========================================

def assert_reservation_consistency(book_id):

    reserved_copies = Copy.query.filter_by(
        book_id=book_id,
        status="RESERVED"
    ).count()

    ready_reservations = Reservation.query.filter_by(
        book_id=book_id,
        status="READY"
    ).count()

    assert reserved_copies == ready_reservations


def get_audit_count(action):

    return AuditLog.query.filter_by(
        action=action
    ).count()


# ==========================================
# INFRASTRUCTURE TESTS
# ==========================================

def test_integration_services_fixture(services):

    assert len(services) == 11

    assert isinstance(
        services["reservation"],
        ReservationService
    )

    assert isinstance(
        services["loan"],
        LoanService
    )

    assert isinstance(
        services["copy"],
        CopyService
    )


def test_integration_admin_account(library):

    admin = library["admin"]

    assert admin.id is not None
    assert admin.role == "ADMIN"
    assert admin.is_active is True


def test_integration_librarian_account(library):

    librarian = library["librarian"]

    assert librarian.id is not None
    assert librarian.role == "LIBRARIAN"
    assert librarian.is_active is True


def test_integration_readers(library):

    assert len(library["readers"]) == 4

    for reader in library["readers"]:

        assert reader.id is not None
        assert reader.user.role == "READER"
        assert reader.user.is_active is True
        assert reader.card_number is not None

    assert Reader.query.count() == 4
    assert User.query.count() == 6


def test_integration_book_collection(library):

    assert len(library["books"]) == 3

    for book in library["books"]:

        assert book.id is not None

        assert book.category_id == (
            library["category"].id
        )

        assert library["author"] in book.authors

        assert book.is_archived is False

    assert Book.query.count() == 3


def test_integration_available_copy(
    library, available_copy
):

    assert available_copy.id is not None
    assert available_copy.status == "AVAILABLE"

    assert available_copy.book_id == (
        library["books"][0].id
    )

    assert Copy.query.count() == 1

    assert_reservation_consistency(
        available_copy.book_id
    )


def test_integration_default_settings(
    services, library
):

    setting = services["setting"]

    assert setting.get_max_loans() == 5
    assert setting.get_loan_days() == 30
    assert setting.get_max_reservations() == 3
    assert setting.get_reservation_days() == 3

    assert setting.get_fine_per_day() == (
        Decimal("1.00")
    )


def test_integration_authentication(
    services, library
):

    user = services["auth"].authenticate(
        library["librarian"].username,
        library["password"]
    )

    assert user.id == library["librarian"].id
    assert user.role == "LIBRARIAN"


def test_integration_empty_operations(library):

    assert Reservation.query.count() == 0
    assert Loan.query.count() == 0
    assert Fine.query.count() == 0

    for book in library["books"]:

        assert_reservation_consistency(book.id)


def test_integration_database_isolation(app):

    assert app.config["TESTING"] is True

    assert app.config["SQLALCHEMY_DATABASE_URI"] == (
        "sqlite:///:memory:"
    )

    assert User.query.count() == 0
    assert Reader.query.count() == 0
    assert Book.query.count() == 0
    assert Copy.query.count() == 0
    assert Loan.query.count() == 0
    assert Reservation.query.count() == 0

# ==========================================
# SC-01 - AVAILABLE BOOK RESERVATION
# ==========================================

def test_scenario_available_book_reservation(
    services, library, available_copy
):

    reservation_service = services["reservation"]
    loan_service = services["loan"]

    reader = library["readers"][0]
    librarian = library["librarian"]
    book = library["books"][0]

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    assert reservation.status == "READY"
    assert available_copy.status == "RESERVED"

    assert_reservation_consistency(book.id)

    loan = reservation_service.fulfill_reservation(
        librarian.id,
        reservation.id
    )

    assert loan.status == "ACTIVE"
    assert loan.reader_id == reader.id
    assert loan.copy_id == available_copy.id

    assert reservation.status == "FULFILLED"
    assert available_copy.status == "LOANED"

    assert_reservation_consistency(book.id)

    loan_service.return_book(
        librarian.id,
        loan.id
    )

    assert loan.status == "RETURNED"
    assert available_copy.status == "AVAILABLE"

    assert Loan.query.count() == 1
    assert Reservation.query.count() == 1
    assert Fine.query.count() == 0

    assert_reservation_consistency(book.id)


# ==========================================
# SC-02 - BORROWED BOOK RESERVATION
# ==========================================

def test_scenario_borrowed_book_reservation(
    services, library, available_copy
):

    loan_service = services["loan"]
    reservation_service = services["reservation"]

    librarian = library["librarian"]
    first_reader = library["readers"][0]
    second_reader = library["readers"][1]
    book = library["books"][0]

    first_loan = loan_service.borrow_book(
        librarian.id,
        first_reader.id,
        available_copy.id
    )

    reservation = reservation_service.create_own_reservation(
        second_reader.user_id,
        book.id
    )

    assert first_loan.status == "ACTIVE"
    assert available_copy.status == "LOANED"

    assert reservation.status == "WAITING"
    assert reservation.expires_at is None

    loan_service.return_book(
        librarian.id,
        first_loan.id
    )

    assert first_loan.status == "RETURNED"
    assert reservation.status == "READY"
    assert available_copy.status == "RESERVED"

    assert_reservation_consistency(book.id)

    second_loan = reservation_service.fulfill_reservation(
        librarian.id,
        reservation.id
    )

    assert second_loan.status == "ACTIVE"
    assert second_loan.reader_id == second_reader.id

    assert reservation.status == "FULFILLED"
    assert available_copy.status == "LOANED"

    assert Loan.query.count() == 2

    assert_reservation_consistency(book.id)


# ==========================================
# SC-03 - THREE READERS FIFO QUEUE
# ==========================================

def test_scenario_three_reader_queue(
    services, library
):

    reservation_service = services["reservation"]
    copy_service = services["copy"]
    loan_service = services["loan"]

    librarian = library["librarian"]
    book = library["books"][0]

    reservations = []

    for reader in library["readers"][:3]:

        reservation = (
            reservation_service.create_own_reservation(
                reader.user_id,
                book.id
            )
        )

        reservations.append(reservation)

    assert all(
        reservation.status == "WAITING"
        for reservation in reservations
    )

    for position, reservation in enumerate(
        reservations,
        start=1
    ):

        assert reservation_service.get_queue_position(
            librarian.id,
            reservation.id
        ) == position

    copy = copy_service.create_copy(
        librarian.id,
        book.id,
        "INTEGRATION-FIFO-001"
    )

    for index, reservation in enumerate(reservations):

        assert reservation.status == "READY"
        assert copy.status == "RESERVED"

        assert_reservation_consistency(book.id)

        assert all(
            item.status == "WAITING"
            for item in reservations[index + 1:]
        )

        loan = reservation_service.fulfill_reservation(
            librarian.id,
            reservation.id
        )

        assert loan.reader_id == reservation.reader_id
        assert loan.copy_id == copy.id

        assert reservation.status == "FULFILLED"
        assert copy.status == "LOANED"

        assert_reservation_consistency(book.id)

        loan_service.return_book(
            librarian.id,
            loan.id
        )

        assert loan.status == "RETURNED"

        assert_reservation_consistency(book.id)

    assert all(
        reservation.status == "FULFILLED"
        for reservation in reservations
    )

    assert copy.status == "AVAILABLE"

    assert Loan.query.count() == 3
    assert Reservation.query.count() == 3
    assert Fine.query.count() == 0


# ==========================================
# SC-04 - NEW BOOK COPY DELIVERY
# ==========================================

def test_scenario_new_copy_delivery(
    services, library
):

    reservation_service = services["reservation"]
    copy_service = services["copy"]

    librarian = library["librarian"]
    book = library["books"][0]

    reservations = []

    for reader in library["readers"][:3]:

        reservations.append(
            reservation_service.create_own_reservation(
                reader.user_id,
                book.id
            )
        )

    copies = []

    for number in range(1, 5):

        copy = copy_service.create_copy(
            librarian.id,
            book.id,
            f"INTEGRATION-DELIVERY-{number:03d}"
        )

        copies.append(copy)

        assert_reservation_consistency(book.id)

    assert all(
        reservation.status == "READY"
        for reservation in reservations
    )

    assert all(
        copy.status == "RESERVED"
        for copy in copies[:3]
    )

    assert copies[3].status == "AVAILABLE"

    assert Copy.query.count() == 4

    assert Copy.query.filter_by(
        book_id=book.id,
        status="RESERVED"
    ).count() == 3

    assert Copy.query.filter_by(
        book_id=book.id,
        status="AVAILABLE"
    ).count() == 1


# ==========================================
# SC-05 - READER CANCELLATION
# ==========================================

def test_scenario_reader_cancellation(
    services, library, available_copy
):

    reservation_service = services["reservation"]

    first_reader = library["readers"][0]
    second_reader = library["readers"][1]
    book = library["books"][0]

    first = reservation_service.create_own_reservation(
        first_reader.user_id,
        book.id
    )

    second = reservation_service.create_own_reservation(
        second_reader.user_id,
        book.id
    )

    assert first.status == "READY"
    assert second.status == "WAITING"

    reservation_service.cancel_reservation(
        first_reader.user_id,
        first.id
    )

    assert first.status == "CANCELLED"
    assert second.status == "READY"

    assert second.expires_at is not None
    assert available_copy.status == "RESERVED"

    assert_reservation_consistency(book.id)

    reservation_service.cancel_reservation(
        second_reader.user_id,
        second.id
    )

    assert second.status == "CANCELLED"
    assert available_copy.status == "AVAILABLE"

    assert Reservation.query.count() == 2
    assert Loan.query.count() == 0

    assert get_audit_count(
        "RESERVATION_CANCELLED"
    ) == 2

    assert_reservation_consistency(book.id)


# ==========================================
# SC-06 - MISSED PICKUP DEADLINE
# ==========================================

def test_scenario_missed_pickup_deadline(
    services, library, available_copy
):

    reservation_service = services["reservation"]

    librarian = library["librarian"]
    first_reader = library["readers"][0]
    second_reader = library["readers"][1]
    book = library["books"][0]

    first = reservation_service.create_own_reservation(
        first_reader.user_id,
        book.id
    )

    second = reservation_service.create_own_reservation(
        second_reader.user_id,
        book.id
    )

    assert first.status == "READY"
    assert second.status == "WAITING"

    # Simulate missed pickup deadline.

    first.expires_at = (
        reservation_service.now()
        - timedelta(minutes=1)
    )

    db.session.commit()

    expired = reservation_service.expire_reservations(
        librarian.id
    )

    assert first.id in {
        item.id for item in expired
    }

    assert first.status == "EXPIRED"
    assert second.status == "READY"

    assert second.expires_at > (
        reservation_service.now()
    )

    assert available_copy.status == "RESERVED"

    assert_reservation_consistency(book.id)

    loan = reservation_service.fulfill_reservation(
        librarian.id,
        second.id
    )

    assert loan.reader_id == second_reader.id
    assert second.status == "FULFILLED"

    assert get_audit_count(
        "RESERVATION_EXPIRED"
    ) == 1

    assert_reservation_consistency(book.id)


# ==========================================
# SC-07 - OVERDUE RETURN AND NEXT RESERVATION
# ==========================================

def test_scenario_overdue_return(
    services, library, available_copy
):

    loan_service = services["loan"]
    reservation_service = services["reservation"]

    librarian = library["librarian"]
    first_reader = library["readers"][0]
    second_reader = library["readers"][1]
    book = library["books"][0]

    services["setting"].update(
        "FINE_PER_DAY",
        Decimal("2.00")
    )

    loan = loan_service.borrow_book(
        librarian.id,
        first_reader.id,
        available_copy.id
    )

    reservation = reservation_service.create_own_reservation(
        second_reader.user_id,
        book.id
    )

    assert reservation.status == "WAITING"

    # Simulate a loan borrowed 35 days ago,
    # with a deadline exceeded by over 5 days.

    now = loan_service.now()

    loan.borrowed_at = now - timedelta(days=35)

    loan.due_date = (
        now - timedelta(days=5)
    )

    db.session.commit()

    loan_service.return_book(
        librarian.id,
        loan.id
    )

    assert loan.status == "RETURNED"
    assert loan.returned_at is not None

    fine = Fine.query.filter_by(
        loan_id=loan.id
    ).one()

    overdue_days = (
        loan_service.get_overdue_days(
            librarian.id,
            loan.id
        )
    )

    assert overdue_days >= 5

    assert fine.amount == (
        Decimal(overdue_days)
        * Decimal("2.00")
    )

    assert fine.status == "UNPAID"

    assert fine.paid_amount == Decimal("0.00")

    assert reservation.status == "READY"
    assert available_copy.status == "RESERVED"

    assert Fine.query.count() == 1

    assert_reservation_consistency(book.id)


# ==========================================
# SC-08 - INDEPENDENT BOOK QUEUES
# ==========================================

def test_scenario_independent_book_queues(
    services, library
):

    reservation_service = services["reservation"]
    copy_service = services["copy"]

    librarian = library["librarian"]
    first_reader = library["readers"][0]
    second_reader = library["readers"][1]

    first_book = library["books"][0]
    second_book = library["books"][1]

    first = reservation_service.create_own_reservation(
        first_reader.user_id,
        first_book.id
    )

    second = reservation_service.create_own_reservation(
        second_reader.user_id,
        second_book.id
    )

    first_copy = copy_service.create_copy(
        librarian.id,
        first_book.id,
        "INTEGRATION-ISOLATION-001"
    )

    assert first.status == "READY"
    assert second.status == "WAITING"

    second_copy = copy_service.create_copy(
        librarian.id,
        second_book.id,
        "INTEGRATION-ISOLATION-002"
    )

    assert second.status == "READY"

    reservation_service.cancel_reservation(
        first_reader.user_id,
        first.id
    )

    assert first.status == "CANCELLED"
    assert first_copy.status == "AVAILABLE"

    assert second.status == "READY"
    assert second_copy.status == "RESERVED"

    assert_reservation_consistency(first_book.id)
    assert_reservation_consistency(second_book.id)


# ==========================================
# SC-09 - REPEATED BORROWING
# ==========================================

def test_scenario_repeated_borrowing(
    services, library, available_copy
):

    reservation_service = services["reservation"]
    loan_service = services["loan"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    first = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    first_loan = reservation_service.fulfill_reservation(
        librarian.id,
        first.id
    )

    loan_service.return_book(
        librarian.id,
        first_loan.id
    )

    assert first_loan.status == "RETURNED"

    second = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    assert second.id != first.id
    assert second.status == "READY"

    second_loan = reservation_service.fulfill_reservation(
        librarian.id,
        second.id
    )

    assert first.status == "FULFILLED"
    assert second.status == "FULFILLED"

    assert first_loan.id != second_loan.id
    assert second_loan.status == "ACTIVE"

    assert Loan.query.count() == 2
    assert Reservation.query.count() == 2

    assert available_copy.status == "LOANED"

    assert_reservation_consistency(book.id)


# ==========================================
# SC-10 - MULTIPLE STAFF MEMBERS
# ==========================================

def test_scenario_multiple_staff_members(
    services, library, available_copy
):

    reservation_service = services["reservation"]
    loan_service = services["loan"]

    admin = library["admin"]
    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    reservation = reservation_service.create_reservation(
        librarian.id,
        reader.id,
        book.id
    )

    loan = reservation_service.fulfill_reservation(
        admin.id,
        reservation.id
    )

    loan_service.return_book(
        librarian.id,
        loan.id
    )

    creation_log = AuditLog.query.filter_by(
        action="RESERVATION_CREATED"
    ).one()

    fulfillment_log = AuditLog.query.filter_by(
        action="RESERVATION_FULFILLED"
    ).one()

    loan_log = AuditLog.query.filter_by(
        action="LOAN_CREATED"
    ).one()

    assert creation_log.user_id == librarian.id

    assert fulfillment_log.user_id == admin.id
    assert loan_log.user_id == admin.id

    assert reservation.status == "FULFILLED"
    assert loan.status == "RETURNED"
    assert available_copy.status == "AVAILABLE"

    assert_reservation_consistency(book.id)




# ==========================================
# INT-01 - RESERVED COPY PROTECTION
# ==========================================

def test_integration_reserved_copy_protection(
    services, library, available_copy
):

    reservation_service = services["reservation"]
    loan_service = services["loan"]

    librarian = library["librarian"]
    first_reader = library["readers"][0]
    second_reader = library["readers"][1]
    book = library["books"][0]

    reservation = reservation_service.create_own_reservation(
        first_reader.user_id,
        book.id
    )

    with pytest.raises(CopyUnavailableError):

        loan_service.borrow_book(
            librarian.id,
            second_reader.id,
            available_copy.id
        )

    assert reservation.status == "READY"
    assert available_copy.status == "RESERVED"

    assert Loan.query.count() == 0

    assert get_audit_count(
        "LOAN_CREATED"
    ) == 0

    assert_reservation_consistency(book.id)


# ==========================================
# INT-02 - SURPLUS COPY BORROWING
# ==========================================

def test_integration_surplus_copy_borrowing(
    services, library, available_copy
):

    reservation_service = services["reservation"]
    loan_service = services["loan"]
    copy_service = services["copy"]

    librarian = library["librarian"]
    first_reader = library["readers"][0]
    second_reader = library["readers"][1]
    book = library["books"][0]

    reservation = reservation_service.create_own_reservation(
        first_reader.user_id,
        book.id
    )

    surplus = copy_service.create_copy(
        librarian.id,
        book.id,
        "INTEGRATION-SURPLUS-001"
    )

    assert surplus.status == "AVAILABLE"

    loan = loan_service.borrow_book(
        librarian.id,
        second_reader.id,
        surplus.id
    )

    assert loan.status == "ACTIVE"
    assert loan.reader_id == second_reader.id
    assert loan.copy_id == surplus.id

    assert surplus.status == "LOANED"

    assert reservation.status == "READY"
    assert available_copy.status == "RESERVED"

    assert_reservation_consistency(book.id)


# ==========================================
# INT-03 - OWN RESERVATION BYPASS
# ==========================================

def test_integration_cannot_bypass_own_reservation(
    services, library, available_copy
):

    reservation_service = services["reservation"]
    loan_service = services["loan"]
    copy_service = services["copy"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    surplus = copy_service.create_copy(
        librarian.id,
        book.id,
        "INTEGRATION-BYPASS-001"
    )

    with pytest.raises(BusinessRuleError):

        loan_service.borrow_book(
            librarian.id,
            reader.id,
            surplus.id
        )

    assert reservation.status == "READY"
    assert available_copy.status == "RESERVED"
    assert surplus.status == "AVAILABLE"

    assert Loan.query.count() == 0

    loan = reservation_service.fulfill_reservation(
        librarian.id,
        reservation.id
    )

    assert reservation.status == "FULFILLED"
    assert loan.status == "ACTIVE"

    assert loan.copy_id == available_copy.id

    assert surplus.status == "AVAILABLE"

    assert_reservation_consistency(book.id)


# ==========================================
# INT-04 - LOAN CANCELLATION AND QUEUE
# ==========================================

def test_integration_loan_cancellation_processes_queue(
    services, library, available_copy
):

    reservation_service = services["reservation"]
    loan_service = services["loan"]

    admin = library["admin"]
    librarian = library["librarian"]

    first_reader = library["readers"][0]
    second_reader = library["readers"][1]
    book = library["books"][0]

    loan = loan_service.borrow_book(
        librarian.id,
        first_reader.id,
        available_copy.id
    )

    reservation = reservation_service.create_own_reservation(
        second_reader.user_id,
        book.id
    )

    assert reservation.status == "WAITING"
    assert available_copy.status == "LOANED"

    loan_service.cancel_loan(
        admin.id,
        loan.id,
        "Incorrect borrowing registration."
    )

    assert loan.status == "CANCELLED"
    assert loan.returned_at is None

    assert reservation.status == "READY"
    assert reservation.expires_at is not None

    assert available_copy.status == "RESERVED"

    assert Fine.query.count() == 0

    assert get_audit_count(
        "LOAN_CANCELLED"
    ) == 1

    assert_reservation_consistency(book.id)


# ==========================================
# INT-05 - ACTIVE LOAN RESERVATION PROTECTION
# ==========================================

def test_integration_cannot_reserve_borrowed_book(
    services, library, available_copy
):

    reservation_service = services["reservation"]
    loan_service = services["loan"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    loan = loan_service.borrow_book(
        librarian.id,
        reader.id,
        available_copy.id
    )

    with pytest.raises(BusinessRuleError):

        reservation_service.create_own_reservation(
            reader.user_id,
            book.id
        )

    assert loan.status == "ACTIVE"
    assert available_copy.status == "LOANED"

    assert Reservation.query.count() == 0

    assert get_audit_count(
        "RESERVATION_CREATED"
    ) == 0

    loan_service.return_book(
        librarian.id,
        loan.id
    )

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    assert loan.status == "RETURNED"
    assert reservation.status == "READY"
    assert available_copy.status == "RESERVED"

    assert_reservation_consistency(book.id)


# ==========================================
# INT-06 - SHARED LOAN LIMIT
# ==========================================

def test_integration_reservation_respects_shared_loan_limit(
    services, library, available_copy
):

    reservation_service = services["reservation"]
    loan_service = services["loan"]
    copy_service = services["copy"]
    setting_service = services["setting"]

    librarian = library["librarian"]
    reader = library["readers"][0]

    first_book = library["books"][0]
    second_book = library["books"][1]

    setting_service.update(
        "MAX_ACTIVE_LOANS",
        1
    )

    second_copy = copy_service.create_copy(
        librarian.id,
        second_book.id,
        "INTEGRATION-LIMIT-001"
    )

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        first_book.id
    )

    existing_loan = loan_service.borrow_book(
        librarian.id,
        reader.id,
        second_copy.id
    )

    with pytest.raises(LoanLimitExceededError):

        reservation_service.fulfill_reservation(
            librarian.id,
            reservation.id
        )

    assert existing_loan.status == "ACTIVE"
    assert reservation.status == "READY"
    assert available_copy.status == "RESERVED"

    assert Loan.query.count() == 1

    loan_service.return_book(
        librarian.id,
        existing_loan.id
    )

    new_loan = reservation_service.fulfill_reservation(
        librarian.id,
        reservation.id
    )

    assert existing_loan.status == "RETURNED"
    assert new_loan.status == "ACTIVE"
    assert reservation.status == "FULFILLED"
    assert available_copy.status == "LOANED"

    assert Loan.query.count() == 2

    assert Loan.query.filter_by(
        reader_id=reader.id,
        status="ACTIVE"
    ).count() == 1

    assert_reservation_consistency(first_book.id)
    assert_reservation_consistency(second_book.id)


# ==========================================
# INT-07 - RETURN TRANSACTION ROLLBACK
# ==========================================

def test_integration_failed_return_rolls_back_queue(
    services, library, available_copy, monkeypatch
):

    reservation_service = services["reservation"]
    loan_service = services["loan"]

    librarian = library["librarian"]
    first_reader = library["readers"][0]
    second_reader = library["readers"][1]
    book = library["books"][0]

    loan = loan_service.borrow_book(
        librarian.id,
        first_reader.id,
        available_copy.id
    )

    reservation = reservation_service.create_own_reservation(
        second_reader.user_id,
        book.id
    )

    audit_count = AuditLog.query.count()

    original_process = (
        loan_service.reservation_service._process_queue
    )

    def fail_queue(*args, **kwargs):

        original_process(*args, **kwargs)

        raise RuntimeError(
            "Simulated queue failure during return."
        )

    with monkeypatch.context() as patch:

        patch.setattr(
            loan_service.reservation_service,
            "_process_queue",
            fail_queue
        )

        with pytest.raises(
            RuntimeError,
            match="Simulated queue failure"
        ):

            loan_service.return_book(
                librarian.id,
                loan.id
            )

    assert loan.status == "ACTIVE"
    assert loan.returned_at is None

    assert reservation.status == "WAITING"
    assert reservation.expires_at is None

    assert available_copy.status == "LOANED"

    assert Fine.query.count() == 0
    assert AuditLog.query.count() == audit_count

    assert_reservation_consistency(book.id)

    # Verify recovery after rollback.

    loan_service.return_book(
        librarian.id,
        loan.id
    )

    assert loan.status == "RETURNED"
    assert reservation.status == "READY"
    assert available_copy.status == "RESERVED"

    assert_reservation_consistency(book.id)


# ==========================================
# INT-08 - FULFILLMENT TRANSACTION ROLLBACK
# ==========================================

def test_integration_failed_fulfillment_rolls_back_loan(
    services, library, available_copy, monkeypatch
):

    reservation_service = services["reservation"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    original_deadline = reservation.expires_at

    audit_count = AuditLog.query.count()

    original_log = reservation_service.audit_service.log

    def fail_audit(action, *args, **kwargs):

        original_log(action, *args, **kwargs)

        if action == "RESERVATION_FULFILLED":

            raise RuntimeError(
                "Simulated fulfillment failure."
            )

    with monkeypatch.context() as patch:

        patch.setattr(
            reservation_service.audit_service,
            "log",
            fail_audit
        )

        with pytest.raises(
            RuntimeError,
            match="Simulated fulfillment failure"
        ):

            reservation_service.fulfill_reservation(
                librarian.id,
                reservation.id
            )

    assert reservation.status == "READY"

    assert reservation.expires_at == original_deadline
    assert available_copy.status == "RESERVED"

    assert Loan.query.count() == 0
    assert AuditLog.query.count() == audit_count

    assert get_audit_count(
        "LOAN_CREATED"
    ) == 0

    assert_reservation_consistency(book.id)

    loan = reservation_service.fulfill_reservation(
        librarian.id,
        reservation.id
    )

    assert loan.status == "ACTIVE"
    assert reservation.status == "FULFILLED"
    assert available_copy.status == "LOANED"

    assert Loan.query.count() == 1

    assert_reservation_consistency(book.id)


# ==========================================
# INT-09 - DATABASE PERSISTENCE
# ==========================================

def test_integration_fulfillment_database_persistence(
    services, library, available_copy
):

    reservation_service = services["reservation"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    loan = reservation_service.fulfill_reservation(
        librarian.id,
        reservation.id
    )

    reservation_id = reservation.id
    loan_id = loan.id
    copy_id = available_copy.id
    reader_id = reader.id
    book_id = book.id
    actor_id = librarian.id

    db.session.remove()

    new_reservation_service = ReservationService()
    new_loan_service = LoanService()
    new_copy_service = CopyService()

    saved_reservation = new_reservation_service.get_by_id(
        actor_id,
        reservation_id
    )

    saved_loan = new_loan_service.get_by_id(
        actor_id,
        loan_id
    )

    saved_copy = new_copy_service.get_by_id(
        actor_id,
        copy_id
    )

    assert saved_reservation.status == "FULFILLED"

    assert saved_loan.status == "ACTIVE"
    assert saved_loan.reader_id == reader_id
    assert saved_loan.copy_id == copy_id

    assert saved_copy.status == "LOANED"
    assert saved_copy.book_id == book_id

    assert get_audit_count(
        "RESERVATION_FULFILLED"
    ) == 1

    assert get_audit_count(
        "LOAN_CREATED"
    ) == 1

    assert_reservation_consistency(book_id)


# ==========================================
# INT-10 - DUPLICATE FULFILLMENT PROTECTION
# ==========================================

def test_integration_duplicate_fulfillment_protection(
    services, library, available_copy
):

    reservation_service = services["reservation"]

    admin = library["admin"]
    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    loan = reservation_service.fulfill_reservation(
        librarian.id,
        reservation.id
    )

    audit_count = AuditLog.query.count()

    second_service = ReservationService()

    with pytest.raises(BusinessRuleError):

        second_service.fulfill_reservation(
            admin.id,
            reservation.id
        )

    assert loan.status == "ACTIVE"
    assert reservation.status == "FULFILLED"
    assert available_copy.status == "LOANED"

    assert Loan.query.count() == 1

    assert get_audit_count(
        "LOAN_CREATED"
    ) == 1

    assert get_audit_count(
        "RESERVATION_FULFILLED"
    ) == 1

    assert AuditLog.query.count() == audit_count

    assert_reservation_consistency(book.id)


# ==========================================
# INT-11 - DAMAGED COPY RESTORATION
# ==========================================

def test_integration_damaged_copy_restoration(
    services, library, available_copy
):

    copy_service = services["copy"]
    reservation_service = services["reservation"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    copy_service.mark_damaged(
        librarian.id,
        available_copy.id
    )

    assert available_copy.status == "DAMAGED"

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    assert reservation.status == "WAITING"
    assert reservation.expires_at is None

    copy_service.restore_availability(
        librarian.id,
        available_copy.id
    )

    assert available_copy.status == "RESERVED"
    assert reservation.status == "READY"
    assert reservation.expires_at is not None

    assert_reservation_consistency(book.id)

    loan = reservation_service.fulfill_reservation(
        librarian.id,
        reservation.id
    )

    assert loan.status == "ACTIVE"
    assert loan.copy_id == available_copy.id

    assert reservation.status == "FULFILLED"
    assert available_copy.status == "LOANED"

    assert_reservation_consistency(book.id)


# ==========================================
# INT-12 - LOST COPY RESTORATION
# ==========================================

def test_integration_lost_copy_restoration(
    services, library, available_copy
):

    copy_service = services["copy"]
    reservation_service = services["reservation"]

    librarian = library["librarian"]
    book = library["books"][0]

    first_reader = library["readers"][0]
    second_reader = library["readers"][1]

    copy_service.mark_lost(
        librarian.id,
        available_copy.id
    )

    assert available_copy.status == "LOST"

    first = reservation_service.create_own_reservation(
        first_reader.user_id,
        book.id
    )

    second = reservation_service.create_own_reservation(
        second_reader.user_id,
        book.id
    )

    assert first.status == "WAITING"
    assert second.status == "WAITING"

    copy_service.restore_availability(
        librarian.id,
        available_copy.id
    )

    assert first.status == "READY"
    assert second.status == "WAITING"

    assert available_copy.status == "RESERVED"

    assert reservation_service.get_queue_position(
        librarian.id,
        second.id
    ) == 1

    assert_reservation_consistency(book.id)


# ==========================================
# INT-13 - RESERVED COPY STATUS PROTECTION
# ==========================================

@pytest.mark.parametrize(
    "method_name",
    [
        "mark_damaged",
        "mark_lost",
        "restore_availability"
    ]
)
def test_integration_reserved_copy_status_protection(
    services, library, available_copy, method_name
):

    copy_service = services["copy"]
    reservation_service = services["reservation"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    audit_count = AuditLog.query.count()

    method = getattr(
        copy_service,
        method_name
    )

    with pytest.raises(BusinessRuleError):

        method(
            librarian.id,
            available_copy.id
        )

    assert reservation.status == "READY"
    assert available_copy.status == "RESERVED"

    assert AuditLog.query.count() == audit_count

    assert Loan.query.count() == 0

    assert_reservation_consistency(book.id)


# ==========================================
# INT-14 - SURPLUS COPY DAMAGE
# ==========================================

def test_integration_surplus_copy_damage(
    services, library, available_copy
):

    copy_service = services["copy"]
    reservation_service = services["reservation"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    surplus = copy_service.create_copy(
        librarian.id,
        book.id,
        "INTEGRATION-DAMAGE-001"
    )

    assert surplus.status == "AVAILABLE"

    copy_service.mark_damaged(
        librarian.id,
        surplus.id
    )

    assert surplus.status == "DAMAGED"
    assert available_copy.status == "RESERVED"
    assert reservation.status == "READY"

    assert_reservation_consistency(book.id)

    copy_service.restore_availability(
        librarian.id,
        surplus.id
    )

    assert surplus.status == "AVAILABLE"
    assert reservation.status == "READY"

    assert_reservation_consistency(book.id)


# ==========================================
# INT-15 - COPY DELETION PROTECTION
# ==========================================

def test_integration_copy_deletion_protection(
    services, library, available_copy
):

    copy_service = services["copy"]
    reservation_service = services["reservation"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    surplus = copy_service.create_copy(
        librarian.id,
        book.id,
        "INTEGRATION-DELETE-001"
    )

    with pytest.raises(BusinessRuleError):

        copy_service.delete_copy(
            librarian.id,
            available_copy.id
        )

    with pytest.raises(BusinessRuleError):

        copy_service.delete_copy(
            librarian.id,
            surplus.id
        )

    assert Copy.query.count() == 2

    assert reservation.status == "READY"
    assert available_copy.status == "RESERVED"
    assert surplus.status == "AVAILABLE"

    assert_reservation_consistency(book.id)

    reservation_service.cancel_reservation(
        reader.user_id,
        reservation.id
    )

    assert reservation.status == "CANCELLED"
    assert available_copy.status == "AVAILABLE"

    copy_service.delete_copy(
        librarian.id,
        surplus.id
    )

    assert Copy.query.count() == 1

    assert Reservation.query.count() == 1

    assert_reservation_consistency(book.id)


# ==========================================
# INT-16 - INVENTORY NUMBER UPDATE
# ==========================================

def test_integration_inventory_number_update(
    services, library, available_copy
):

    copy_service = services["copy"]
    reservation_service = services["reservation"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    original_number = available_copy.inventory_number

    with pytest.raises(BusinessRuleError):

        copy_service.update_copy(
            librarian.id,
            available_copy.id,
            "INTEGRATION-UPDATED-001"
        )

    assert available_copy.inventory_number == (
        original_number
    )

    assert reservation.status == "READY"

    surplus = copy_service.create_copy(
        librarian.id,
        book.id,
        "INTEGRATION-UPDATE-002"
    )

    updated = copy_service.update_copy(
        librarian.id,
        surplus.id,
        "INTEGRATION-UPDATED-002"
    )

    assert updated.inventory_number == (
        "INTEGRATION-UPDATED-002"
    )

    assert updated.status == "AVAILABLE"

    assert available_copy.status == "RESERVED"
    assert reservation.status == "READY"

    assert_reservation_consistency(book.id)


# ==========================================
# INT-17 - COPY CREATION ROLLBACK
# ==========================================

def test_integration_copy_creation_rollback(
    services, library, monkeypatch
):

    copy_service = services["copy"]
    reservation_service = services["reservation"]

    librarian = library["librarian"]
    book = library["books"][0]

    reader = library["readers"][0]

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    assert reservation.status == "WAITING"

    audit_count = AuditLog.query.count()

    original_process = (
        copy_service.reservation_service._process_queue
    )

    def fail_queue(*args, **kwargs):

        original_process(*args, **kwargs)

        raise RuntimeError(
            "Simulated copy creation failure."
        )

    with monkeypatch.context() as patch:

        patch.setattr(
            copy_service.reservation_service,
            "_process_queue",
            fail_queue
        )

        with pytest.raises(
            RuntimeError,
            match="Simulated copy creation failure"
        ):

            copy_service.create_copy(
                librarian.id,
                book.id,
                "INTEGRATION-ROLLBACK-001"
            )

    assert Copy.query.count() == 0

    assert reservation.status == "WAITING"
    assert reservation.expires_at is None

    assert AuditLog.query.count() == audit_count

    assert_reservation_consistency(book.id)

    # Verify recovery after rollback.

    copy = copy_service.create_copy(
        librarian.id,
        book.id,
        "INTEGRATION-ROLLBACK-001"
    )

    assert copy.status == "RESERVED"
    assert reservation.status == "READY"

    assert Copy.query.count() == 1

    assert_reservation_consistency(book.id)


# ==========================================
# INT-18 - AVAILABILITY RESTORATION ROLLBACK
# ==========================================

@pytest.mark.parametrize(
    "initial_status",
    ["DAMAGED", "LOST"]
)
def test_integration_copy_restoration_rollback(
    services, library, available_copy,
    monkeypatch, initial_status
):

    copy_service = services["copy"]
    reservation_service = services["reservation"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    copy_service.change_status(
        librarian.id,
        available_copy.id,
        initial_status
    )

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    audit_count = AuditLog.query.count()

    original_process = (
        copy_service.reservation_service._process_queue
    )

    def fail_queue(*args, **kwargs):

        original_process(*args, **kwargs)

        raise RuntimeError(
            "Simulated restoration failure."
        )

    with monkeypatch.context() as patch:

        patch.setattr(
            copy_service.reservation_service,
            "_process_queue",
            fail_queue
        )

        with pytest.raises(
            RuntimeError,
            match="Simulated restoration failure"
        ):

            copy_service.restore_availability(
                librarian.id,
                available_copy.id
            )

    assert available_copy.status == initial_status

    assert reservation.status == "WAITING"
    assert reservation.expires_at is None

    assert AuditLog.query.count() == audit_count

    assert_reservation_consistency(book.id)

    copy_service.restore_availability(
        librarian.id,
        available_copy.id
    )

    assert available_copy.status == "RESERVED"
    assert reservation.status == "READY"

    assert_reservation_consistency(book.id)


# ==========================================
# INT-19 - MULTIPLE COPY ALLOCATION
# ==========================================

def test_integration_multiple_copy_allocation(
    services, library
):

    copy_service = services["copy"]
    reservation_service = services["reservation"]

    librarian = library["librarian"]
    book = library["books"][0]

    first_copy = copy_service.create_copy(
        librarian.id,
        book.id,
        "INTEGRATION-POOL-001"
    )

    second_copy = copy_service.create_copy(
        librarian.id,
        book.id,
        "INTEGRATION-POOL-002"
    )

    copy_service.mark_damaged(
        librarian.id,
        first_copy.id
    )

    copy_service.mark_lost(
        librarian.id,
        second_copy.id
    )

    reservations = []

    for reader in library["readers"][:3]:

        reservations.append(
            reservation_service.create_own_reservation(
                reader.user_id,
                book.id
            )
        )

    assert all(
        item.status == "WAITING"
        for item in reservations
    )

    copy_service.restore_availability(
        librarian.id,
        second_copy.id
    )

    assert reservations[0].status == "READY"
    assert reservations[1].status == "WAITING"
    assert reservations[2].status == "WAITING"

    copy_service.restore_availability(
        librarian.id,
        first_copy.id
    )

    assert reservations[0].status == "READY"
    assert reservations[1].status == "READY"
    assert reservations[2].status == "WAITING"

    third_copy = copy_service.create_copy(
        librarian.id,
        book.id,
        "INTEGRATION-POOL-003"
    )

    assert all(
        item.status == "READY"
        for item in reservations
    )

    assert all(
        item.status == "RESERVED"
        for item in [
            first_copy,
            second_copy,
            third_copy
        ]
    )

    assert Copy.query.count() == 3

    assert_reservation_consistency(book.id)


# ==========================================
# INT-20 - BOOK CATALOG AVAILABILITY
# ==========================================

def test_integration_book_catalog_availability(
    services, library, available_copy
):

    book_service = services["book"]
    copy_service = services["copy"]
    reservation_service = services["reservation"]
    loan_service = services["loan"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    def check_availability(
        available, reserved, loaned, damaged
    ):

        result = book_service.get_availability(
            librarian.id,
            book.id
        )

        assert result["available"] == available
        assert result["reserved"] == reserved
        assert result["loaned"] == loaned
        assert result["damaged"] == damaged
        assert result["lost"] == 0

        assert result["total"] == (
            available + reserved + loaned + damaged
        )

        assert result["is_available"] == (
            available > 0
        )

        assert_reservation_consistency(book.id)

    check_availability(1, 0, 0, 0)

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    check_availability(0, 1, 0, 0)

    surplus = copy_service.create_copy(
        librarian.id,
        book.id,
        "INTEGRATION-CATALOG-001"
    )

    check_availability(1, 1, 0, 0)

    copy_service.mark_damaged(
        librarian.id,
        surplus.id
    )

    check_availability(0, 1, 0, 1)

    loan = reservation_service.fulfill_reservation(
        librarian.id,
        reservation.id
    )

    check_availability(0, 0, 1, 1)

    loan_service.return_book(
        librarian.id,
        loan.id
    )

    check_availability(1, 0, 0, 1)

    copy_service.restore_availability(
        librarian.id,
        surplus.id
    )

    check_availability(2, 0, 0, 0)



# ==========================================
# INT-21 - CUSTOM RESERVATION PICKUP PERIOD
# ==========================================

@pytest.mark.parametrize(
    "reservation_days",
    [1, 7, 14]
)
def test_integration_custom_reservation_period(
    services, library, available_copy,
    reservation_days
):

    setting_service = services["setting"]
    reservation_service = services["reservation"]

    reader = library["readers"][0]
    book = library["books"][0]

    setting_service.update(
        "RESERVATION_PERIOD_DAYS",
        reservation_days
    )

    before = reservation_service.now()

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    after = reservation_service.now()

    assert reservation.status == "READY"

    assert (
        before + timedelta(days=reservation_days)
        <= reservation.expires_at
        <= after + timedelta(days=reservation_days)
    )

    assert available_copy.status == "RESERVED"

    assert_reservation_consistency(book.id)


# ==========================================
# INT-22 - EXISTING RESERVATION DEADLINE
# ==========================================

def test_integration_existing_deadline_preserved(
    services, library, available_copy
):

    setting_service = services["setting"]
    reservation_service = services["reservation"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    original_deadline = reservation.expires_at

    setting_service.update(
        "RESERVATION_PERIOD_DAYS",
        14
    )

    reservation_service.process_queue(
        librarian.id,
        book.id
    )

    assert reservation.status == "READY"
    assert available_copy.status == "RESERVED"

    assert reservation.expires_at == (
        original_deadline
    )

    assert setting_service.get_reservation_days() == 14

    assert_reservation_consistency(book.id)


# ==========================================
# INT-23 - QUEUE USES CURRENT SETTINGS
# ==========================================

def test_integration_queue_uses_current_settings(
    services, library
):

    reservation_service = services["reservation"]
    setting_service = services["setting"]
    copy_service = services["copy"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    assert reservation.status == "WAITING"
    assert reservation.expires_at is None

    setting_service.update(
        "RESERVATION_PERIOD_DAYS",
        10
    )

    before = reservation_service.now()

    copy = copy_service.create_copy(
        librarian.id,
        book.id,
        "INTEGRATION-SETTINGS-001"
    )

    after = reservation_service.now()

    assert reservation.status == "READY"
    assert copy.status == "RESERVED"

    assert (
        before + timedelta(days=10)
        <= reservation.expires_at
        <= after + timedelta(days=10)
    )

    assert_reservation_consistency(book.id)


# ==========================================
# INT-24 - DYNAMIC RESERVATION LIMIT
# ==========================================

def test_integration_dynamic_reservation_limit(
    services, library
):

    setting_service = services["setting"]
    reservation_service = services["reservation"]

    reader = library["readers"][0]
    books = library["books"]

    setting_service.update(
        "MAX_ACTIVE_RESERVATIONS",
        1
    )

    first = reservation_service.create_own_reservation(
        reader.user_id,
        books[0].id
    )

    assert first.status == "WAITING"

    with pytest.raises(
        ReservationLimitExceededError
    ):

        reservation_service.create_own_reservation(
            reader.user_id,
            books[1].id
        )

    assert Reservation.query.count() == 1

    setting_service.update(
        "MAX_ACTIVE_RESERVATIONS",
        2
    )

    second = reservation_service.create_own_reservation(
        reader.user_id,
        books[1].id
    )

    assert second.status == "WAITING"

    assert reservation_service.count_active_by_reader(
        reader.user_id,
        reader.id
    ) == 2

    setting_service.update(
        "MAX_ACTIVE_RESERVATIONS",
        1
    )

    assert reservation_service.get_remaining_reservation_limit(
        reader.user_id,
        reader.id
    ) == 0

    assert first.status == "WAITING"
    assert second.status == "WAITING"

    with pytest.raises(
        ReservationLimitExceededError
    ):

        reservation_service.create_own_reservation(
            reader.user_id,
            books[2].id
        )

    assert Reservation.query.count() == 2


# ==========================================
# INT-25 - RESET SETTINGS TO DEFAULTS
# ==========================================

def test_integration_reset_settings_to_defaults(
    services, library, available_copy
):

    setting_service = services["setting"]
    reservation_service = services["reservation"]

    reader = library["readers"][0]
    book = library["books"][0]

    setting_service.update(
        "RESERVATION_PERIOD_DAYS",
        14
    )

    setting_service.update(
        "MAX_ACTIVE_RESERVATIONS",
        8
    )

    setting_service.update(
        "MAX_ACTIVE_LOANS",
        10
    )

    setting_service.update(
        "LOAN_PERIOD_DAYS",
        60
    )

    setting_service.reset_to_defaults()

    assert setting_service.get_reservation_days() == 3
    assert setting_service.get_max_reservations() == 3
    assert setting_service.get_max_loans() == 5
    assert setting_service.get_loan_days() == 30

    before = reservation_service.now()

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    after = reservation_service.now()

    assert reservation.status == "READY"

    assert (
        before + timedelta(days=3)
        <= reservation.expires_at
        <= after + timedelta(days=3)
    )

    assert available_copy.status == "RESERVED"

    assert_reservation_consistency(book.id)


# ==========================================
# INT-26 - SHARED LOAN PERIOD CONFIGURATION
# ==========================================

def test_integration_shared_loan_period(
    services, library, available_copy
):

    setting_service = services["setting"]
    reservation_service = services["reservation"]
    loan_service = services["loan"]
    copy_service = services["copy"]

    librarian = library["librarian"]

    first_reader = library["readers"][0]
    second_reader = library["readers"][1]

    first_book = library["books"][0]
    second_book = library["books"][1]

    setting_service.update(
        "LOAN_PERIOD_DAYS",
        21
    )

    second_copy = copy_service.create_copy(
        librarian.id,
        second_book.id,
        "INTEGRATION-LOAN-PERIOD-001"
    )

    reservation = reservation_service.create_own_reservation(
        first_reader.user_id,
        first_book.id
    )

    reserved_loan = reservation_service.fulfill_reservation(
        librarian.id,
        reservation.id
    )

    ordinary_loan = loan_service.borrow_book(
        librarian.id,
        second_reader.id,
        second_copy.id
    )

    assert reserved_loan.due_date == (
        reserved_loan.borrowed_at
        + timedelta(days=21)
    )

    assert ordinary_loan.due_date == (
        ordinary_loan.borrowed_at
        + timedelta(days=21)
    )

    setting_service.update(
        "LOAN_PERIOD_DAYS",
        45
    )

    assert reserved_loan.due_date == (
        reserved_loan.borrowed_at
        + timedelta(days=21)
    )

    assert ordinary_loan.due_date == (
        ordinary_loan.borrowed_at
        + timedelta(days=21)
    )

    assert reserved_loan.status == "ACTIVE"
    assert ordinary_loan.status == "ACTIVE"

    assert reservation.status == "FULFILLED"

    assert_reservation_consistency(first_book.id)
    assert_reservation_consistency(second_book.id)


# ==========================================
# INT-27 - RESERVATION AUDIT LIFECYCLE
# ==========================================

def test_integration_reservation_audit_lifecycle(
    services, library
):

    reservation_service = services["reservation"]
    copy_service = services["copy"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    copy = copy_service.create_copy(
        librarian.id,
        book.id,
        "INTEGRATION-AUDIT-001"
    )

    loan = reservation_service.fulfill_reservation(
        librarian.id,
        reservation.id
    )

    actions = [
        "RESERVATION_CREATED",
        "RESERVATION_READY",
        "LOAN_CREATED",
        "RESERVATION_FULFILLED"
    ]

    logs = AuditLog.query.filter(
        AuditLog.action.in_(actions)
    ).order_by(
        AuditLog.id.asc()
    ).all()

    assert [
        log.action for log in logs
    ] == actions

    assert all(
        log.created_at is not None
        for log in logs
    )

    assert (
        f"Reservation ID: {reservation.id}"
        in logs[0].description
    )

    assert (
        f"Loan ID: {loan.id}"
        in logs[-1].description
    )

    assert reservation.status == "FULFILLED"
    assert loan.status == "ACTIVE"
    assert copy.status == "LOANED"

    assert_reservation_consistency(book.id)


# ==========================================
# INT-28 - AUDIT ACTOR ATTRIBUTION
# ==========================================

def test_integration_audit_actor_attribution(
    services, library
):

    reservation_service = services["reservation"]
    copy_service = services["copy"]
    audit_service = services["audit"]

    admin = library["admin"]
    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    copy_service.create_copy(
        librarian.id,
        book.id,
        "INTEGRATION-ACTOR-001"
    )

    reservation_service.cancel_reservation(
        admin.id,
        reservation.id
    )

    created = audit_service.get_by_action(
        "RESERVATION_CREATED"
    )

    ready = audit_service.get_by_action(
        "RESERVATION_READY"
    )

    cancelled = audit_service.get_by_action(
        "RESERVATION_CANCELLED"
    )

    assert len(created) == 1
    assert len(ready) == 1
    assert len(cancelled) == 1

    assert created[0].user_id == reader.user_id
    assert ready[0].user_id == librarian.id
    assert cancelled[0].user_id == admin.id

    assert reservation.status == "CANCELLED"

    assert_reservation_consistency(book.id)


# ==========================================
# INT-29 - REJECTED OPERATION AUDIT INTEGRITY
# ==========================================

def test_integration_rejected_operation_audit_integrity(
    services, library, available_copy
):

    reservation_service = services["reservation"]

    first_reader = library["readers"][0]
    second_reader = library["readers"][1]

    book = library["books"][0]

    reservation = reservation_service.create_own_reservation(
        first_reader.user_id,
        book.id
    )

    audit_count = AuditLog.query.count()

    with pytest.raises(
        ReservationAlreadyExistsError
    ):

        reservation_service.create_own_reservation(
            first_reader.user_id,
            book.id
        )

    with pytest.raises(AuthorizationError):

        reservation_service.cancel_reservation(
            second_reader.user_id,
            reservation.id
        )

    with pytest.raises(AuthorizationError):

        reservation_service.fulfill_reservation(
            first_reader.user_id,
            reservation.id
        )

    assert AuditLog.query.count() == audit_count

    assert reservation.status == "READY"
    assert available_copy.status == "RESERVED"

    assert Reservation.query.count() == 1
    assert Loan.query.count() == 0

    assert get_audit_count(
        "RESERVATION_CANCELLED"
    ) == 0

    assert get_audit_count(
        "RESERVATION_FULFILLED"
    ) == 0

    assert_reservation_consistency(book.id)


# ==========================================
# INT-30 - AUDIT DATABASE PERSISTENCE
# ==========================================

def test_integration_audit_database_persistence(
    services, library, available_copy
):

    reservation_service = services["reservation"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    loan = reservation_service.fulfill_reservation(
        librarian.id,
        reservation.id
    )

    reservation_id = reservation.id
    loan_id = loan.id

    reader_user_id = reader.user_id
    librarian_id = librarian.id

    original_logs = AuditLog.query.filter(
        AuditLog.action.in_([
            "RESERVATION_CREATED",
            "RESERVATION_READY",
            "LOAN_CREATED",
            "RESERVATION_FULFILLED"
        ])
    ).order_by(
        AuditLog.id.asc()
    ).all()

    expected = [
        (
            log.id,
            log.action,
            log.user_id,
            log.description,
            log.created_at
        )
        for log in original_logs
    ]

    assert len(expected) == 4

    db.session.remove()

    new_audit_service = AuditService()

    for saved in expected:

        log = new_audit_service.get_by_id(
            saved[0]
        )

        assert (
            log.id,
            log.action,
            log.user_id,
            log.description,
            log.created_at
        ) == saved

    created = new_audit_service.get_by_action(
        "RESERVATION_CREATED"
    )

    fulfilled = new_audit_service.get_by_action(
        "RESERVATION_FULFILLED"
    )

    assert len(created) == 1
    assert len(fulfilled) == 1

    assert created[0].user_id == reader_user_id
    assert fulfilled[0].user_id == librarian_id

    assert (
        f"Reservation ID: {reservation_id}"
        in fulfilled[0].description
    )

    assert (
        f"Loan ID: {loan_id}"
        in fulfilled[0].description
    )



# ==========================================
# INT-31 - READER DATA ACCESS ISOLATION
# ==========================================

def test_integration_reader_data_isolation(
    services, library, available_copy
):

    reservation_service = services["reservation"]
    loan_service = services["loan"]

    librarian = library["librarian"]

    first_reader = library["readers"][0]
    second_reader = library["readers"][1]

    book = library["books"][0]

    first = reservation_service.create_own_reservation(
        first_reader.user_id,
        book.id
    )

    second = reservation_service.create_own_reservation(
        second_reader.user_id,
        book.id
    )

    assert first.status == "READY"
    assert second.status == "WAITING"

    with pytest.raises(AuthorizationError):

        reservation_service.get_by_id(
            second_reader.user_id,
            first.id
        )

    with pytest.raises(AuthorizationError):

        reservation_service.get_by_reader(
            second_reader.user_id,
            first_reader.id
        )

    with pytest.raises(AuthorizationError):

        reservation_service.get_queue_position(
            second_reader.user_id,
            first.id
        )

    with pytest.raises(AuthorizationError):

        reservation_service.cancel_reservation(
            second_reader.user_id,
            first.id
        )

    own_reservations = (
        reservation_service.get_own_reservations(
            second_reader.user_id
        )
    )

    assert [
        item.id for item in own_reservations
    ] == [second.id]

    loan = reservation_service.fulfill_reservation(
        librarian.id,
        first.id
    )

    with pytest.raises(AuthorizationError):

        loan_service.get_by_id(
            second_reader.user_id,
            loan.id
        )

    assert first.status == "FULFILLED"
    assert second.status == "WAITING"
    assert loan.status == "ACTIVE"

    assert_reservation_consistency(book.id)


# ==========================================
# INT-32 - INACTIVE ACCOUNT ACCESS
# ==========================================

def test_integration_inactive_reader_access(
    services, library
):

    from app.exceptions import InactiveAccountError

    reservation_service = services["reservation"]
    user_service = services["user"]

    admin = library["admin"]
    reader = library["readers"][0]

    first_book = library["books"][0]
    second_book = library["books"][1]

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        first_book.id
    )

    user_service.deactivate_user(
        admin.id,
        reader.user_id
    )

    assert reader.user.is_active is False

    audit_count = AuditLog.query.count()

    with pytest.raises(InactiveAccountError):

        reservation_service.create_own_reservation(
            reader.user_id,
            second_book.id
        )

    with pytest.raises(InactiveAccountError):

        reservation_service.get_own_reservations(
            reader.user_id
        )

    with pytest.raises(InactiveAccountError):

        reservation_service.cancel_reservation(
            reader.user_id,
            reservation.id
        )

    assert Reservation.query.count() == 1
    assert reservation.status == "WAITING"

    assert AuditLog.query.count() == audit_count

    user_service.activate_user(
        admin.id,
        reader.user_id
    )

    assert reader.user.is_active is True

    result = reservation_service.get_own_reservations(
        reader.user_id
    )

    assert len(result) == 1
    assert result[0].id == reservation.id


# ==========================================
# INT-33 - INACTIVE READER IN FIFO QUEUE
# ==========================================

def test_integration_queue_skips_deactivated_reader(
    services, library
):

    reservation_service = services["reservation"]
    user_service = services["user"]
    copy_service = services["copy"]

    admin = library["admin"]
    librarian = library["librarian"]

    first_reader = library["readers"][0]
    second_reader = library["readers"][1]
    third_reader = library["readers"][2]

    book = library["books"][0]

    first = reservation_service.create_own_reservation(
        first_reader.user_id,
        book.id
    )

    second = reservation_service.create_own_reservation(
        second_reader.user_id,
        book.id
    )

    third = reservation_service.create_own_reservation(
        third_reader.user_id,
        book.id
    )

    user_service.deactivate_user(
        admin.id,
        first_reader.user_id
    )

    copy = copy_service.create_copy(
        librarian.id,
        book.id,
        "INTEGRATION-INACTIVE-001"
    )

    assert first.status == "CANCELLED"
    assert first.expires_at is None

    assert second.status == "READY"
    assert third.status == "WAITING"

    assert copy.status == "RESERVED"

    assert reservation_service.get_queue_position(
        librarian.id,
        third.id
    ) == 1

    log = AuditLog.query.filter_by(
        action="RESERVATION_CANCELLED"
    ).one()

    assert log.user_id == librarian.id
    assert "Inactive reader" in log.description

    assert_reservation_consistency(book.id)


# ==========================================
# INT-34 - INACTIVE READER FULFILLMENT
# ==========================================

def test_integration_inactive_reader_fulfillment(
    services, library, available_copy
):

    reservation_service = services["reservation"]
    user_service = services["user"]

    admin = library["admin"]
    librarian = library["librarian"]

    first_reader = library["readers"][0]
    second_reader = library["readers"][1]

    book = library["books"][0]

    first = reservation_service.create_own_reservation(
        first_reader.user_id,
        book.id
    )

    second = reservation_service.create_own_reservation(
        second_reader.user_id,
        book.id
    )

    user_service.deactivate_user(
        admin.id,
        first_reader.user_id
    )

    audit_count = AuditLog.query.count()

    with pytest.raises(BusinessRuleError):

        reservation_service.fulfill_reservation(
            librarian.id,
            first.id
        )

    assert first.status == "READY"
    assert second.status == "WAITING"
    assert available_copy.status == "RESERVED"

    assert Loan.query.count() == 0
    assert AuditLog.query.count() == audit_count

    # Staff cancels the inactive reader's reservation.

    reservation_service.cancel_reservation(
        librarian.id,
        first.id
    )

    assert first.status == "CANCELLED"
    assert second.status == "READY"

    loan = reservation_service.fulfill_reservation(
        librarian.id,
        second.id
    )

    assert loan.reader_id == second_reader.id
    assert loan.status == "ACTIVE"

    assert second.status == "FULFILLED"
    assert available_copy.status == "LOANED"

    assert_reservation_consistency(book.id)


# ==========================================
# INT-35 - BOOK ARCHIVING PROTECTION
# ==========================================

@pytest.mark.parametrize(
    "reservation_status",
    ["WAITING", "READY"]
)
def test_integration_book_archive_protection(
    services, library, reservation_status
):

    reservation_service = services["reservation"]
    book_service = services["book"]
    copy_service = services["copy"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    if reservation_status == "READY":

        copy_service.create_copy(
            librarian.id,
            book.id,
            "INTEGRATION-ARCHIVE-001"
        )

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    assert reservation.status == reservation_status

    audit_count = AuditLog.query.count()

    with pytest.raises(BusinessRuleError):

        book_service.archive_book(
            librarian.id,
            book.id
        )

    assert book.is_archived is False

    assert reservation.status == reservation_status

    assert AuditLog.query.count() == audit_count

    reservation_service.cancel_reservation(
        reader.user_id,
        reservation.id
    )

    book_service.archive_book(
        librarian.id,
        book.id
    )

    assert book.is_archived is True
    assert reservation.status == "CANCELLED"

    assert_reservation_consistency(book.id)


# ==========================================
# INT-36 - ARCHIVED BOOK RESERVATION
# ==========================================

def test_integration_cannot_reserve_archived_book(
    services, library, available_copy
):

    reservation_service = services["reservation"]
    book_service = services["book"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    book_service.archive_book(
        librarian.id,
        book.id
    )

    assert book.is_archived is True

    audit_count = AuditLog.query.count()

    with pytest.raises(BusinessRuleError):

        reservation_service.create_own_reservation(
            reader.user_id,
            book.id
        )

    with pytest.raises(BusinessRuleError):

        reservation_service.create_reservation(
            librarian.id,
            reader.id,
            book.id
        )

    assert Reservation.query.count() == 0
    assert Loan.query.count() == 0

    assert book.is_archived is True

    assert available_copy.status == "AVAILABLE"

    assert AuditLog.query.count() == audit_count

    assert_reservation_consistency(book.id)


# ==========================================
# INT-37 - ARCHIVED BOOK RESTORATION
# ==========================================

def test_integration_restored_book_reservation(
    services, library, available_copy
):

    reservation_service = services["reservation"]
    book_service = services["book"]

    librarian = library["librarian"]
    reader = library["readers"][0]
    book = library["books"][0]

    book_service.archive_book(
        librarian.id,
        book.id
    )

    with pytest.raises(BusinessRuleError):

        reservation_service.create_own_reservation(
            reader.user_id,
            book.id
        )

    book_service.restore_book(
        librarian.id,
        book.id
    )

    assert book.is_archived is False

    reservation = reservation_service.create_own_reservation(
        reader.user_id,
        book.id
    )

    assert reservation.status == "READY"
    assert available_copy.status == "RESERVED"

    loan = reservation_service.fulfill_reservation(
        librarian.id,
        reservation.id
    )

    assert reservation.status == "FULFILLED"
    assert loan.status == "ACTIVE"

    assert loan.reader_id == reader.id
    assert loan.copy_id == available_copy.id

    assert_reservation_consistency(book.id)


# ==========================================
# INT-38 - INDEPENDENT READER LIMITS
# ==========================================

def test_integration_independent_reader_limits(
    services, library
):

    reservation_service = services["reservation"]
    setting_service = services["setting"]

    first_reader = library["readers"][0]
    second_reader = library["readers"][1]

    first_book = library["books"][0]
    second_book = library["books"][1]

    setting_service.update(
        "MAX_ACTIVE_RESERVATIONS",
        1
    )

    first = reservation_service.create_own_reservation(
        first_reader.user_id,
        first_book.id
    )

    second = reservation_service.create_own_reservation(
        second_reader.user_id,
        first_book.id
    )

    assert first.status == "WAITING"
    assert second.status == "WAITING"

    for reader in [first_reader, second_reader]:

        assert reservation_service.count_active_by_reader(
            reader.user_id,
            reader.id
        ) == 1

        with pytest.raises(
            ReservationLimitExceededError
        ):

            reservation_service.create_own_reservation(
                reader.user_id,
                second_book.id
            )

    reservation_service.cancel_reservation(
        first_reader.user_id,
        first.id
    )

    third = reservation_service.create_own_reservation(
        first_reader.user_id,
        second_book.id
    )

    assert first.status == "CANCELLED"
    assert second.status == "WAITING"
    assert third.status == "WAITING"

    with pytest.raises(
        ReservationLimitExceededError
    ):

        reservation_service.create_own_reservation(
            second_reader.user_id,
            second_book.id
        )

    assert Reservation.query.count() == 3

    assert_reservation_consistency(first_book.id)
    assert_reservation_consistency(second_book.id)


# ==========================================
# INT-39 - LIMIT AND DUPLICATE PROTECTION
# ==========================================

def test_integration_limit_and_duplicate_protection(
    services, library, available_copy
):

    reservation_service = services["reservation"]
    setting_service = services["setting"]

    librarian = library["librarian"]
    reader = library["readers"][0]

    books = library["books"]

    setting_service.update(
        "MAX_ACTIVE_RESERVATIONS",
        2
    )

    first = reservation_service.create_own_reservation(
        reader.user_id,
        books[0].id
    )

    assert first.status == "READY"

    with pytest.raises(
        ReservationAlreadyExistsError
    ):

        reservation_service.create_reservation(
            librarian.id,
            reader.id,
            books[0].id
        )

    second = reservation_service.create_own_reservation(
        reader.user_id,
        books[1].id
    )

    assert second.status == "WAITING"

    with pytest.raises(
        ReservationLimitExceededError
    ):

        reservation_service.create_own_reservation(
            reader.user_id,
            books[2].id
        )

    loan = reservation_service.fulfill_reservation(
        librarian.id,
        first.id
    )

    third = reservation_service.create_own_reservation(
        reader.user_id,
        books[2].id
    )

    assert first.status == "FULFILLED"
    assert second.status == "WAITING"
    assert third.status == "WAITING"

    assert loan.status == "ACTIVE"
    assert available_copy.status == "LOANED"

    assert reservation_service.count_active_by_reader(
        reader.user_id,
        reader.id
    ) == 2

    assert Reservation.query.count() == 3
    assert Loan.query.count() == 1

    for book in books:

        assert_reservation_consistency(book.id)


# ==========================================
# INT-40 - EXPIRATION RELEASES READER LIMIT
# ==========================================

def test_integration_expiration_releases_reader_limit(
    services, library, available_copy
):

    reservation_service = services["reservation"]
    setting_service = services["setting"]

    librarian = library["librarian"]
    reader = library["readers"][0]

    first_book = library["books"][0]
    second_book = library["books"][1]

    setting_service.update(
        "MAX_ACTIVE_RESERVATIONS",
        1
    )

    first = reservation_service.create_own_reservation(
        reader.user_id,
        first_book.id
    )

    assert first.status == "READY"

    with pytest.raises(
        ReservationLimitExceededError
    ):

        reservation_service.create_own_reservation(
            reader.user_id,
            second_book.id
        )

    # Simulate an exceeded pickup deadline.

    first.expires_at = (
        reservation_service.now()
        - timedelta(minutes=1)
    )

    db.session.commit()

    expired = reservation_service.expire_reservations(
        librarian.id
    )

    assert first.id in {
        item.id for item in expired
    }

    assert first.status == "EXPIRED"
    assert available_copy.status == "AVAILABLE"

    assert reservation_service.get_remaining_reservation_limit(
        reader.user_id,
        reader.id
    ) == 1

    second = reservation_service.create_own_reservation(
        reader.user_id,
        second_book.id
    )

    assert second.status == "WAITING"

    assert reservation_service.get_remaining_reservation_limit(
        reader.user_id,
        reader.id
    ) == 0

    assert Reservation.query.count() == 2

    assert get_audit_count(
        "RESERVATION_EXPIRED"
    ) == 1

    assert_reservation_consistency(first_book.id)
    assert_reservation_consistency(second_book.id)