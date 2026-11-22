from datetime import timedelta
from decimal import Decimal

import pytest

from app.extensions import db

from app.models import (
    User,
    Reader,
    Category,
    Author,
    Book,
    Copy,
    Loan,
    Reservation,
    Fine,
    Payment,
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
    FineService,
    SettingService,
    AuditService
)

from app.exceptions import (
    ValidationError,
    BusinessRuleError,
    NotFoundError,
    AuthenticationError,
    AuthorizationError,
    InactiveAccountError,
    LoanAlreadyReturnedError,
    DatabaseError
)


# ==========================================
# INTEGRATION SERVICE FIXTURE
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
        "fine": FineService(),
        "setting": SettingService(),
        "audit": AuditService()
    }


# ==========================================
# INTEGRATION LIBRARY FIXTURE
# ==========================================

@pytest.fixture
def library(services):

    services["setting"].initialize_defaults()

    password = "FineIntegrationPassword123!"

    admin = User(
        username="fine_integration_admin",
        email="admin@fine-integration.example.com",
        password_hash=services["auth"].hash_password(
            password
        ),
        role="ADMIN",
        is_active=True
    )

    db.session.add(admin)

    db.session.commit()

    librarian = services["user"].create_user(
        admin.id,
        "fine_integration_librarian",
        "librarian@fine-integration.example.com",
        password,
        role="LIBRARIAN"
    )

    readers = []

    for number in range(1, 4):

        reader = services["reader"].register_reader(
            librarian.id,
            f"fine_integration_reader{number}",
            f"reader{number}@fine-integration.example.com",
            password,
            "Jan",
            "Kowalski"
        )

        readers.append(reader)

    category = services["category"].create_category(
        librarian.id,
        "Fantasy",
        "Fantasy literature"
    )

    author = services["author"].create_author(
        librarian.id,
        "Andrzej",
        "Sapkowski"
    )

    books = []

    for number in range(1, 4):

        book = services["book"].create_book(
            librarian.id,
            title=f"Fine integration book {number}",
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
        "reader": readers[0],
        "other_reader": readers[1],
        "category": category,
        "author": author,
        "books": books,
        "book": books[0],
        "password": password
    }


# ==========================================
# AVAILABLE COPY FIXTURE
# ==========================================

@pytest.fixture
def available_copy(services, library):

    return services["copy"].create_copy(
        library["librarian"].id,
        library["book"].id,
        "FINE-INTEGRATION-001"
    )


# ==========================================
# ACTIVE LOAN FIXTURE
# ==========================================

@pytest.fixture
def active_loan(
    services,
    library,
    available_copy
):

    return services["loan"].borrow_book(
        library["librarian"].id,
        library["reader"].id,
        available_copy.id
    )


# ==========================================
# OVERDUE LOAN HELPER
# ==========================================

def make_loan_overdue(
    services,
    loan,
    days
):

    if type(days) is not int or days < 1:

        raise ValueError(
            "Overdue days must be positive."
        )

    now = services["loan"].now()

    loan.due_date = (
        now - timedelta(
            days=days - 1,
            hours=12
        )
    )

    loan.borrowed_at = (
        loan.due_date - timedelta(
            days=services["setting"].get_loan_days()
        )
    )

    db.session.commit()

    return loan


# ==========================================
# OVERDUE LOAN FIXTURE
# ==========================================

@pytest.fixture
def overdue_loan(
    services,
    active_loan
):

    return make_loan_overdue(
        services,
        active_loan,
        6
    )


# ==========================================
# RETURNED LOAN WITH FINE FIXTURE
# ==========================================

@pytest.fixture
def recorded_fine(
    services,
    library,
    overdue_loan
):

    actor_id = library["librarian"].id

    loan = services["loan"].return_book(
        actor_id,
        overdue_loan.id
    )

    fine = services["fine"].get_by_loan(
        actor_id,
        loan.id
    )

    assert fine is not None

    return fine


# ==========================================
# AUDIT HELPER
# ==========================================

def get_audit_count(action):

    return AuditLog.query.filter_by(
        action=action
    ).count()


# ==========================================
# PAYMENT TOTAL HELPER
# ==========================================

def get_payment_total(fine_id):

    payments = Payment.query.filter_by(
        fine_id=fine_id
    ).all()

    return sum(
        (
            payment.amount
            for payment in payments
        ),
        Decimal("0.00")
    )


# ==========================================
# FINANCIAL INTEGRITY HELPER
# ==========================================

def assert_financial_integrity():

    fines = Fine.query.all()

    for fine in fines:

        assert fine.amount > Decimal("0.00")

        assert fine.paid_amount >= Decimal("0.00")

        assert fine.paid_amount <= fine.amount

        assert fine.loan is not None

        assert fine.loan.status == "RETURNED"

        assert fine.loan.returned_at is not None

        assert (
            fine.loan.returned_at
            > fine.loan.due_date
        )

        assert get_payment_total(
            fine.id
        ) == fine.paid_amount

        if fine.paid_amount == Decimal("0.00"):

            assert fine.status == "UNPAID"

        elif fine.paid_amount == fine.amount:

            assert fine.status == "PAID"

        else:

            assert fine.status == "PARTIALLY_PAID"

    payments = Payment.query.all()

    for payment in payments:

        assert payment.fine is not None

        assert payment.amount > Decimal("0.00")

        assert payment.method in (
            "CASH",
            "CARD"
        )


# ==========================================
# RESERVATION INTEGRITY HELPER
# ==========================================

def assert_reservation_integrity(book_id):

    reserved_copies = Copy.query.filter_by(
        book_id=book_id,
        status="RESERVED"
    ).count()

    ready_reservations = Reservation.query.filter_by(
        book_id=book_id,
        status="READY"
    ).count()

    assert reserved_copies == ready_reservations


# ==========================================
# SERVICE INFRASTRUCTURE TEST
# ==========================================

def test_fine_integration_services(services):

    expected_services = {
        "auth": AuthService,
        "user": UserService,
        "reader": ReaderService,
        "category": CategoryService,
        "author": AuthorService,
        "book": BookService,
        "copy": CopyService,
        "loan": LoanService,
        "reservation": ReservationService,
        "fine": FineService,
        "setting": SettingService,
        "audit": AuditService
    }

    assert len(services) == 12

    for name, service_class in expected_services.items():

        assert isinstance(
            services[name],
            service_class
        )

    assert isinstance(
        services["loan"].fine_service,
        FineService
    )

    assert (
        services["loan"].fine_service.repository
        is services["loan"].fine_repository
    )


# ==========================================
# LIBRARY USERS TEST
# ==========================================

def test_fine_integration_library_users(
    services,
    library
):

    admin = library["admin"]

    librarian = library["librarian"]

    password = library["password"]

    assert User.query.count() == 5

    assert Reader.query.count() == 3

    assert admin.role == "ADMIN"

    assert librarian.role == "LIBRARIAN"

    assert admin.is_active is True

    assert librarian.is_active is True

    assert admin.password_hash != password

    assert librarian.password_hash != password

    assert services["auth"].require_admin(
        admin.id
    ).id == admin.id

    assert services["auth"].require_staff(
        librarian.id
    ).id == librarian.id

    for reader in library["readers"]:

        assert reader.user.role == "READER"

        assert reader.user.is_active is True

        assert reader.user.password_hash != password

        own_profile = (
            services["reader"].get_own_profile(
                reader.user_id
            )
        )

        assert own_profile.id == reader.id


# ==========================================
# LIBRARY CATALOG TEST
# ==========================================

def test_fine_integration_library_catalog(
    library
):

    assert Category.query.count() == 1

    assert Author.query.count() == 1

    assert Book.query.count() == 3

    for book in library["books"]:

        assert book.is_archived is False

        assert book.category_id == (
            library["category"].id
        )

        assert {
            author.id
            for author in book.authors
        } == {
            library["author"].id
        }

    assert Copy.query.count() == 0

    assert Loan.query.count() == 0

    assert Fine.query.count() == 0


# ==========================================
# AVAILABLE COPY TEST
# ==========================================

def test_fine_integration_available_copy(
    services,
    library,
    available_copy
):

    assert available_copy.id is not None

    assert available_copy.status == "AVAILABLE"

    assert available_copy.book_id == (
        library["book"].id
    )

    availability = services["book"].get_availability(
        library["librarian"].id,
        library["book"].id
    )

    assert availability["total"] == 1

    assert availability["available"] == 1

    assert availability["is_available"] is True

    assert Loan.query.count() == 0

    assert Fine.query.count() == 0

    assert_reservation_integrity(
        library["book"].id
    )


# ==========================================
# ACTIVE LOAN TEST
# ==========================================

def test_fine_integration_active_loan(
    services,
    library,
    available_copy,
    active_loan
):

    actor_id = library["librarian"].id

    assert active_loan.status == "ACTIVE"

    assert active_loan.copy_id == (
        available_copy.id
    )

    assert active_loan.reader_id == (
        library["reader"].id
    )

    assert available_copy.status == "LOANED"

    assert active_loan.returned_at is None

    assert Loan.query.count() == 1

    assert Fine.query.count() == 0

    assert services["fine"].get_by_loan(
        actor_id,
        active_loan.id
    ) is None

    assert services["loan"].calculate_fine(
        actor_id,
        active_loan.id
    ) == Decimal("0.00")

    assert services["fine"].get_own_total_unpaid(
        library["reader"].user_id
    ) == Decimal("0.00")


# ==========================================
# OVERDUE LOAN TEST
# ==========================================

def test_fine_integration_overdue_loan(
    services,
    library,
    overdue_loan
):

    actor_id = library["librarian"].id

    assert overdue_loan.status == "ACTIVE"

    assert services["loan"].is_overdue(
        actor_id,
        overdue_loan.id
    ) is True

    assert services["loan"].get_overdue_days(
        actor_id,
        overdue_loan.id
    ) == 6

    assert services["loan"].calculate_fine(
        actor_id,
        overdue_loan.id
    ) == Decimal("6.00")

    assert services["fine"].get_by_loan(
        actor_id,
        overdue_loan.id
    ) is None

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0

    assert get_audit_count(
        "FINE_CREATED"
    ) == 0


# ==========================================
# RECORDED FINE TEST
# ==========================================

def test_fine_integration_recorded_fine(
    services,
    library,
    recorded_fine
):

    actor_id = library["librarian"].id

    reader = library["reader"]

    assert recorded_fine.id is not None

    assert recorded_fine.amount == (
        Decimal("6.00")
    )

    assert recorded_fine.paid_amount == (
        Decimal("0.00")
    )

    assert recorded_fine.status == "UNPAID"

    assert recorded_fine.loan.status == "RETURNED"

    assert recorded_fine.loan.copy.status == (
        "AVAILABLE"
    )

    assert recorded_fine.loan.reader_id == (
        reader.id
    )

    assert services["fine"].get_remaining_amount(
        actor_id,
        recorded_fine.id
    ) == Decimal("6.00")

    assert services["fine"].get_own_total_unpaid(
        reader.user_id
    ) == Decimal("6.00")

    assert Fine.query.count() == 1

    assert Payment.query.count() == 0

    assert get_audit_count(
        "FINE_CREATED"
    ) == 1

    assert get_audit_count(
        "LOAN_RETURNED"
    ) == 1

    assert_financial_integrity()

    assert_reservation_integrity(
        library["book"].id
    )


# ==========================================
# INTEGRATION DATABASE ISOLATION
# ==========================================

def test_fine_integration_database_isolation(app):

    assert app.config["TESTING"] is True

    assert app.config[
        "SQLALCHEMY_DATABASE_URI"
    ] == "sqlite:///:memory:"

    assert User.query.count() == 0

    assert Reader.query.count() == 0

    assert Category.query.count() == 0

    assert Author.query.count() == 0

    assert Book.query.count() == 0

    assert Copy.query.count() == 0

    assert Loan.query.count() == 0

    assert Reservation.query.count() == 0

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0

    assert AuditLog.query.count() == 0



# ==========================================
# LIBRARY SCENARIO HELPERS
# ==========================================

def create_integration_fine(
    services,
    library,
    reader,
    days,
    inventory_number,
    book=None
):

    actor_id = library["librarian"].id

    if book is None:
        book = library["book"]

    copy = services["copy"].create_copy(
        actor_id,
        book.id,
        inventory_number
    )

    loan = services["loan"].borrow_book(
        actor_id,
        reader.id,
        copy.id
    )

    make_loan_overdue(
        services,
        loan,
        days
    )

    loan = services["loan"].return_book(
        actor_id,
        loan.id
    )

    fine = services["fine"].get_by_loan(
        actor_id,
        loan.id
    )

    assert fine is not None

    return fine


# ==========================================
# SIMULATED PAYMENT HELPER
# ==========================================

def simulate_fine_payment(
    fine,
    amount,
    method="CASH"
):

    # Test-only helper.
    # PaymentService is not implemented yet.

    amount = Decimal(amount)

    assert amount > Decimal("0.00")

    assert method in ("CASH", "CARD")

    new_paid_amount = (
        fine.paid_amount + amount
    )

    assert new_paid_amount <= fine.amount

    payment = Payment(
        fine_id=fine.id,
        amount=amount,
        method=method
    )

    db.session.add(payment)

    fine.paid_amount = new_paid_amount

    if new_paid_amount == fine.amount:

        fine.status = "PAID"

    else:

        fine.status = "PARTIALLY_PAID"

    db.session.commit()

    return payment


# ==========================================
# COMPLETE FINE LIFECYCLE
# ==========================================

def test_fine_integration_complete_lifecycle(
    services,
    library,
    overdue_loan
):

    actor_id = library["librarian"].id

    reader = library["reader"]

    loan_id = overdue_loan.id

    # Stage 1: active overdue loan.

    assert overdue_loan.status == "ACTIVE"

    assert services["loan"].calculate_fine(
        actor_id,
        loan_id
    ) == Decimal("6.00")

    assert services["fine"].get_own_total_unpaid(
        reader.user_id
    ) == Decimal("0.00")

    # Stage 2: return and fine creation.

    loan = services["loan"].return_book(
        actor_id,
        loan_id
    )

    fine = services["fine"].get_by_loan(
        actor_id,
        loan.id
    )

    assert loan.status == "RETURNED"

    assert fine.amount == Decimal("6.00")

    assert fine.status == "UNPAID"

    assert services["fine"].get_remaining_amount(
        actor_id,
        fine.id
    ) == Decimal("6.00")

    # Stage 3: partial payment.

    simulate_fine_payment(
        fine,
        "2.00",
        "CASH"
    )

    assert fine.status == "PARTIALLY_PAID"

    assert services["fine"].get_own_total_unpaid(
        reader.user_id
    ) == Decimal("4.00")

    # Stage 4: full settlement.

    simulate_fine_payment(
        fine,
        "4.00",
        "CARD"
    )

    assert fine.status == "PAID"

    assert fine.paid_amount == Decimal("6.00")

    assert services["fine"].get_own_total_unpaid(
        reader.user_id
    ) == Decimal("0.00")

    assert services["fine"].get_own_unpaid_fines(
        reader.user_id
    ) == []

    # Historical records remain available.

    assert len(
        services["fine"].get_own_fines(
            reader.user_id
        )
    ) == 1

    assert Fine.query.count() == 1

    assert Payment.query.count() == 2

    assert get_audit_count("FINE_CREATED") == 1

    assert get_audit_count("LOAN_RETURNED") == 1

    assert_financial_integrity()


# ==========================================
# ON-TIME RETURN SCENARIO
# ==========================================

def test_fine_integration_on_time_return(
    services,
    library,
    active_loan
):

    actor_id = library["librarian"].id

    loan = services["loan"].return_book(
        actor_id,
        active_loan.id
    )

    assert loan.status == "RETURNED"

    assert loan.returned_at <= loan.due_date

    assert loan.copy.status == "AVAILABLE"

    assert services["fine"].get_by_loan(
        actor_id,
        loan.id
    ) is None

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0

    assert get_audit_count("FINE_CREATED") == 0

    assert get_audit_count("LOAN_RETURNED") == 1

    assert_financial_integrity()


# ==========================================
# DIFFERENT DAILY RATES
# ==========================================

@pytest.mark.parametrize(
    "rate, expected",
    [
        ("0.00", "0.00"),
        ("0.25", "1.50"),
        ("1.00", "6.00"),
        ("2.50", "15.00")
    ]
)
def test_fine_integration_return_daily_rates(
    services,
    library,
    overdue_loan,
    rate,
    expected
):

    actor_id = library["librarian"].id

    services["setting"].update(
        "FINE_PER_DAY",
        Decimal(rate)
    )

    expected_amount = Decimal(expected)

    estimate = services["loan"].calculate_fine(
        actor_id,
        overdue_loan.id
    )

    assert estimate == expected_amount

    loan = services["loan"].return_book(
        actor_id,
        overdue_loan.id
    )

    fine = services["fine"].get_by_loan(
        actor_id,
        loan.id
    )

    assert loan.status == "RETURNED"

    assert loan.copy.status == "AVAILABLE"

    if expected_amount == Decimal("0.00"):

        assert fine is None

        assert Fine.query.count() == 0

        assert get_audit_count("FINE_CREATED") == 0

    else:

        assert fine is not None

        assert fine.amount == expected_amount

        assert fine.status == "UNPAID"

        assert Fine.query.count() == 1

        assert get_audit_count("FINE_CREATED") == 1

    assert_financial_integrity()


# ==========================================
# REPEATED COPY BORROWING
# ==========================================

def test_fine_integration_repeated_copy_borrowing(
    services,
    library,
    available_copy
):

    actor_id = library["librarian"].id

    reader = library["reader"]

    copy_id = available_copy.id

    loan_ids = []

    fine_ids = []

    for days in [3, 7, 10]:

        loan = services["loan"].borrow_book(
            actor_id,
            reader.id,
            copy_id
        )

        make_loan_overdue(
            services,
            loan,
            days
        )

        loan = services["loan"].return_book(
            actor_id,
            loan.id
        )

        fine = services["fine"].get_by_loan(
            actor_id,
            loan.id
        )

        assert fine.amount == Decimal(days)

        assert loan.copy.status == "AVAILABLE"

        loan_ids.append(loan.id)

        fine_ids.append(fine.id)

    assert len(set(loan_ids)) == 3

    assert len(set(fine_ids)) == 3

    assert Copy.query.count() == 1

    assert Loan.query.count() == 3

    assert Fine.query.count() == 3

    assert services["fine"].get_own_total_unpaid(
        reader.user_id
    ) == Decimal("20.00")

    assert_financial_integrity()


# ==========================================
# MULTIPLE FINES FOR ONE READER
# ==========================================

def test_fine_integration_multiple_reader_fines(
    services,
    library
):

    actor_id = library["librarian"].id

    reader = library["reader"]

    for index, days in enumerate(
        [5, 10, 15],
        start=1
    ):

        create_integration_fine(
            services,
            library,
            reader,
            days,
            f"READER-FINE-{index:03d}",
            book=library["books"][index - 1]
        )

    fines = services["fine"].get_by_reader(
        actor_id,
        reader.id
    )

    assert len(fines) == 3

    assert all(
        fine.loan.reader_id == reader.id
        for fine in fines
    )

    summary = services["fine"].get_own_summary(
        reader.user_id
    )

    assert summary["total_fines"] == 3

    assert summary["unpaid_fines"] == 3

    assert summary["total_amount"] == (
        Decimal("30.00")
    )

    assert summary["total_unpaid"] == (
        Decimal("30.00")
    )

    assert summary["total_paid"] == (
        Decimal("0.00")
    )

    assert_financial_integrity()


# ==========================================
# INDEPENDENT READER BALANCES
# ==========================================

def test_fine_integration_independent_balances(
    services,
    library
):

    first_reader = library["readers"][0]

    second_reader = library["readers"][1]

    third_reader = library["readers"][2]

    first_fine = create_integration_fine(
        services,
        library,
        first_reader,
        10,
        "BALANCE-001"
    )

    second_fine = create_integration_fine(
        services,
        library,
        second_reader,
        25,
        "BALANCE-002"
    )

    simulate_fine_payment(
        first_fine,
        "4.00"
    )

    simulate_fine_payment(
        second_fine,
        "5.00"
    )

    assert services["fine"].get_own_total_unpaid(
        first_reader.user_id
    ) == Decimal("6.00")

    assert services["fine"].get_own_total_unpaid(
        second_reader.user_id
    ) == Decimal("20.00")

    assert services["fine"].get_own_total_unpaid(
        third_reader.user_id
    ) == Decimal("0.00")

    global_summary = services["fine"].get_summary(
        library["admin"].id
    )

    assert global_summary["total_amount"] == (
        Decimal("35.00")
    )

    assert global_summary["total_paid"] == (
        Decimal("9.00")
    )

    assert global_summary["total_unpaid"] == (
        Decimal("26.00")
    )

    assert global_summary["total_fines"] == 2

    assert_financial_integrity()


# ==========================================
# RATE CHANGE DURING ACTIVE LOAN
# ==========================================

def test_fine_integration_rate_change_active_loan(
    services,
    library,
    overdue_loan
):

    actor_id = library["librarian"].id

    loan_id = overdue_loan.id

    assert services["loan"].calculate_fine(
        actor_id,
        loan_id
    ) == Decimal("6.00")

    services["setting"].update(
        "FINE_PER_DAY",
        Decimal("3.00")
    )

    assert services["loan"].calculate_fine(
        actor_id,
        loan_id
    ) == Decimal("18.00")

    assert Fine.query.count() == 0

    services["loan"].return_book(
        actor_id,
        loan_id
    )

    fine = services["fine"].get_by_loan(
        actor_id,
        loan_id
    )

    assert fine.amount == Decimal("18.00")

    assert fine.status == "UNPAID"

    assert get_audit_count("FINE_CREATED") == 1

    assert_financial_integrity()


# ==========================================
# HISTORICAL FINE PROTECTION
# ==========================================

def test_fine_integration_historical_rate_protection(
    services,
    library,
    recorded_fine
):

    actor_id = library["librarian"].id

    reader = library["reader"]

    assert recorded_fine.amount == (
        Decimal("6.00")
    )

    services["setting"].update(
        "FINE_PER_DAY",
        Decimal("5.00")
    )

    second_fine = create_integration_fine(
        services,
        library,
        reader,
        6,
        "HISTORY-002"
    )

    assert recorded_fine.amount == (
        Decimal("6.00")
    )

    assert second_fine.amount == (
        Decimal("30.00")
    )

    summary = services["fine"].get_summary(
        actor_id
    )

    assert summary["total_fines"] == 2

    assert summary["total_amount"] == (
        Decimal("36.00")
    )

    assert summary["total_unpaid"] == (
        Decimal("36.00")
    )

    assert services["loan"].calculate_fine(
        actor_id,
        recorded_fine.loan_id
    ) == Decimal("6.00")

    assert_financial_integrity()


# ==========================================
# MULTIPLE PARTIAL PAYMENTS
# ==========================================

def test_fine_integration_multiple_partial_payments(
    services,
    library,
    recorded_fine
):

    reader = library["reader"]

    simulate_fine_payment(
        recorded_fine,
        "1.25",
        "CASH"
    )

    assert services["fine"].get_own_total_unpaid(
        reader.user_id
    ) == Decimal("4.75")

    simulate_fine_payment(
        recorded_fine,
        "2.50",
        "CARD"
    )

    assert recorded_fine.status == (
        "PARTIALLY_PAID"
    )

    assert recorded_fine.paid_amount == (
        Decimal("3.75")
    )

    assert services["fine"].get_own_total_unpaid(
        reader.user_id
    ) == Decimal("2.25")

    assert Payment.query.count() == 2

    assert get_payment_total(
        recorded_fine.id
    ) == Decimal("3.75")

    assert_financial_integrity()


# ==========================================
# COMPLETE READER DEBT SETTLEMENT
# ==========================================

def test_fine_integration_complete_debt_settlement(
    services,
    library
):

    actor_id = library["librarian"].id

    reader = library["reader"]

    fines = []

    for index, days in enumerate(
        [10, 20, 30],
        start=1
    ):

        fine = create_integration_fine(
            services,
            library,
            reader,
            days,
            f"SETTLEMENT-{index:03d}"
        )

        fines.append(fine)

    assert services["fine"].get_own_total_unpaid(
        reader.user_id
    ) == Decimal("60.00")

    for fine in fines:

        remaining = (
            services["fine"].get_remaining_amount(
                actor_id,
                fine.id
            )
        )

        simulate_fine_payment(
            fine,
            remaining,
            "CARD"
        )

    summary = services["fine"].get_own_summary(
        reader.user_id
    )

    assert summary["total_fines"] == 3

    assert summary["paid_fines"] == 3

    assert summary["unpaid_fines"] == 0

    assert summary["partially_paid_fines"] == 0

    assert summary["total_amount"] == (
        Decimal("60.00")
    )

    assert summary["total_paid"] == (
        Decimal("60.00")
    )

    assert summary["total_unpaid"] == (
        Decimal("0.00")
    )

    assert services["fine"].get_own_unpaid_fines(
        reader.user_id
    ) == []

    assert Fine.query.count() == 3

    assert Payment.query.count() == 3

    assert_financial_integrity()


# ==========================================
# CANCELLED LOAN WITHOUT FINE
# ==========================================

def test_fine_integration_cancelled_loan(
    services,
    library,
    active_loan
):

    actor_id = library["admin"].id

    loan = services["loan"].cancel_loan(
        actor_id,
        active_loan.id,
        "Integration test cancellation"
    )

    assert loan.status == "CANCELLED"

    assert loan.returned_at is None

    assert loan.copy.status == "AVAILABLE"

    assert services["fine"].get_by_loan(
        actor_id,
        loan.id
    ) is None

    assert services["loan"].calculate_fine(
        actor_id,
        loan.id
    ) == Decimal("0.00")

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0

    assert get_audit_count("FINE_CREATED") == 0

    assert_financial_integrity()


# ==========================================
# INACTIVE READER FINANCIAL HISTORY
# ==========================================

def test_fine_integration_inactive_reader_history(
    services,
    library,
    recorded_fine
):

    admin_id = library["admin"].id

    reader = library["reader"]

    reader_id = reader.id

    reader_user_id = reader.user_id

    fine_id = recorded_fine.id

    services["user"].deactivate_user(
        admin_id,
        reader_user_id
    )

    assert reader.user.is_active is False

    with pytest.raises(InactiveAccountError):

        services["fine"].get_own_fines(
            reader_user_id
        )

    with pytest.raises(InactiveAccountError):

        services["fine"].get_own_summary(
            reader_user_id
        )

    # Deactivation must not delete financial history.

    fine = services["fine"].get_by_id(
        admin_id,
        fine_id
    )

    assert fine.loan.reader_id == reader_id

    assert fine.amount == Decimal("6.00")

    assert fine.status == "UNPAID"

    assert Fine.query.count() == 1

    assert_financial_integrity()


# ==========================================
# FINANCIAL DATA SESSION RELOADING
# ==========================================

def test_fine_integration_session_reloading(
    services,
    library,
    recorded_fine
):

    actor_id = library["admin"].id

    reader_user_id = library["reader"].user_id

    fine_id = recorded_fine.id

    simulate_fine_payment(
        recorded_fine,
        "2.50",
        "CARD"
    )

    original_summary = (
        services["fine"].get_summary(actor_id)
    )

    db.session.remove()

    fresh_service = FineService()

    fine = fresh_service.get_by_id(
        actor_id,
        fine_id
    )

    assert fine.amount == Decimal("6.00")

    assert fine.paid_amount == Decimal("2.50")

    assert fine.status == "PARTIALLY_PAID"

    assert fresh_service.get_remaining_amount(
        actor_id,
        fine_id
    ) == Decimal("3.50")

    assert fresh_service.get_own_total_unpaid(
        reader_user_id
    ) == Decimal("3.50")

    assert fresh_service.get_summary(
        actor_id
    ) == original_summary

    assert Payment.query.count() == 1

    assert_financial_integrity()


# ==========================================
# FINANCIAL AUDIT CORRELATION
# ==========================================

def test_fine_integration_audit_correlation(
    services,
    library
):

    actor_id = library["librarian"].id

    reader = library["reader"]

    fines = []

    for index, days in enumerate(
        [3, 6, 9],
        start=1
    ):

        fine = create_integration_fine(
            services,
            library,
            reader,
            days,
            f"AUDIT-FINE-{index:03d}"
        )

        fines.append(fine)

    audits = services["audit"].get_by_action(
        "FINE_CREATED"
    )

    assert len(audits) == 3

    for fine in fines:

        expected_description = (
            f"Fine ID: {fine.id}; "
            f"Loan ID: {fine.loan_id}; "
            f"Amount: {fine.amount} PLN"
        )

        matching = [
            audit
            for audit in audits
            if audit.description == expected_description
        ]

        assert len(matching) == 1

        assert matching[0].user_id == actor_id

        assert matching[0].created_at is not None

        assert matching[0].created_at.tzinfo is None

    assert get_audit_count("LOAN_RETURNED") == 3

    assert Fine.query.count() == 3

    assert Payment.query.count() == 0

    assert_financial_integrity()


# ==========================================
# FINE AND RESERVATION INTEGRATION
# ==========================================

@pytest.fixture
def waiting_reservation(
    services,
    library,
    overdue_loan
):

    reservation = services["reservation"].create_own_reservation(
        library["other_reader"].user_id,
        library["book"].id
    )

    assert reservation.status == "WAITING"

    assert reservation.expires_at is None

    assert overdue_loan.copy.status == "LOANED"

    return reservation


# ==========================================
# OVERDUE RETURN WITH WAITING RESERVATION
# ==========================================

def test_fine_reservation_overdue_return(
    services,
    library,
    overdue_loan,
    waiting_reservation
):

    actor_id = library["librarian"].id

    loan = services["loan"].return_book(
        actor_id,
        overdue_loan.id
    )

    fine = services["fine"].get_by_loan(
        actor_id,
        loan.id
    )

    assert loan.status == "RETURNED"

    assert fine is not None

    assert fine.amount == Decimal("6.00")

    assert fine.status == "UNPAID"

    assert waiting_reservation.status == "READY"

    assert waiting_reservation.expires_at is not None

    assert loan.copy.status == "RESERVED"

    assert Fine.query.count() == 1

    assert Payment.query.count() == 0

    assert_financial_integrity()

    assert_reservation_integrity(
        library["book"].id
    )


# ==========================================
# RETURN WITHOUT WAITING RESERVATIONS
# ==========================================

def test_fine_reservation_no_waiting_records(
    services,
    library,
    overdue_loan
):

    actor_id = library["librarian"].id

    loan = services["loan"].return_book(
        actor_id,
        overdue_loan.id
    )

    assert loan.status == "RETURNED"

    assert loan.copy.status == "AVAILABLE"

    assert loan.fine is not None

    assert loan.fine.amount == Decimal("6.00")

    assert Reservation.query.count() == 0

    assert_financial_integrity()

    assert_reservation_integrity(
        library["book"].id
    )


# ==========================================
# ON-TIME RETURN WITH RESERVATION
# ==========================================

def test_fine_reservation_on_time_return(
    services,
    library,
    active_loan
):

    actor_id = library["librarian"].id

    reservation = services["reservation"].create_own_reservation(
        library["other_reader"].user_id,
        library["book"].id
    )

    assert reservation.status == "WAITING"

    loan = services["loan"].return_book(
        actor_id,
        active_loan.id
    )

    assert loan.status == "RETURNED"

    assert loan.copy.status == "RESERVED"

    assert reservation.status == "READY"

    assert reservation.expires_at is not None

    assert services["fine"].get_by_loan(
        actor_id,
        loan.id
    ) is None

    assert Fine.query.count() == 0

    assert get_audit_count("FINE_CREATED") == 0

    assert_financial_integrity()

    assert_reservation_integrity(
        library["book"].id
    )


# ==========================================
# ZERO FINE RATE WITH RESERVATION
# ==========================================

def test_fine_reservation_zero_daily_rate(
    services,
    library,
    overdue_loan,
    waiting_reservation
):

    actor_id = library["librarian"].id

    services["setting"].update(
        "FINE_PER_DAY",
        Decimal("0.00")
    )

    loan = services["loan"].return_book(
        actor_id,
        overdue_loan.id
    )

    assert loan.status == "RETURNED"

    assert loan.copy.status == "RESERVED"

    assert waiting_reservation.status == "READY"

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0

    assert get_audit_count("FINE_CREATED") == 0

    assert_financial_integrity()

    assert_reservation_integrity(
        library["book"].id
    )


# ==========================================
# FIFO RESERVATION QUEUE
# ==========================================

def test_fine_reservation_fifo_queue(
    services,
    library,
    overdue_loan,
    waiting_reservation
):

    actor_id = library["librarian"].id

    third_reader = library["readers"][2]

    second_reservation = services["reservation"].create_own_reservation(
        third_reader.user_id,
        library["book"].id
    )

    assert waiting_reservation.status == "WAITING"

    assert second_reservation.status == "WAITING"

    loan = services["loan"].return_book(
        actor_id,
        overdue_loan.id
    )

    assert loan.fine.amount == Decimal("6.00")

    assert waiting_reservation.status == "READY"

    assert second_reservation.status == "WAITING"

    assert loan.copy.status == "RESERVED"

    assert services["reservation"].get_queue_position(
        actor_id,
        waiting_reservation.id
    ) == 0

    assert services["reservation"].get_queue_position(
        actor_id,
        second_reservation.id
    ) == 1

    assert_financial_integrity()

    assert_reservation_integrity(
        library["book"].id
    )


# ==========================================
# RESERVATION FULFILLMENT AFTER FINE
# ==========================================

def test_fine_reservation_fulfillment(
    services,
    library,
    overdue_loan,
    waiting_reservation
):

    actor_id = library["librarian"].id

    old_loan = services["loan"].return_book(
        actor_id,
        overdue_loan.id
    )

    old_fine_id = old_loan.fine.id

    new_loan = services["reservation"].fulfill_reservation(
        actor_id,
        waiting_reservation.id
    )

    assert waiting_reservation.status == "FULFILLED"

    assert new_loan.status == "ACTIVE"

    assert new_loan.copy_id == old_loan.copy_id

    assert new_loan.reader_id == (
        library["other_reader"].id
    )

    assert new_loan.copy.status == "LOANED"

    assert old_loan.status == "RETURNED"

    old_fine = services["fine"].get_by_id(
        actor_id,
        old_fine_id
    )

    assert old_fine.amount == Decimal("6.00")

    assert old_fine.status == "UNPAID"

    assert services["fine"].get_by_loan(
        actor_id,
        new_loan.id
    ) is None

    assert Fine.query.count() == 1

    assert Loan.query.count() == 2

    assert_financial_integrity()

    assert_reservation_integrity(
        library["book"].id
    )


# ==========================================
# MULTIPLE READERS USING THE SAME COPY
# ==========================================

def test_fine_reservation_multiple_readers(
    services,
    library,
    overdue_loan,
    waiting_reservation
):

    actor_id = library["librarian"].id

    first_reader = library["reader"]

    second_reader = library["other_reader"]

    first_loan = services["loan"].return_book(
        actor_id,
        overdue_loan.id
    )

    second_loan = services["reservation"].fulfill_reservation(
        actor_id,
        waiting_reservation.id
    )

    assert second_loan.copy_id == first_loan.copy_id

    make_loan_overdue(
        services,
        second_loan,
        10
    )

    second_loan = services["loan"].return_book(
        actor_id,
        second_loan.id
    )

    assert first_loan.fine.amount == Decimal("6.00")

    assert second_loan.fine.amount == Decimal("10.00")

    assert first_loan.fine.id != second_loan.fine.id

    assert first_loan.fine.loan.reader_id == (
        first_reader.id
    )

    assert second_loan.fine.loan.reader_id == (
        second_reader.id
    )

    assert services["fine"].get_own_total_unpaid(
        first_reader.user_id
    ) == Decimal("6.00")

    assert services["fine"].get_own_total_unpaid(
        second_reader.user_id
    ) == Decimal("10.00")

    summary = services["fine"].get_summary(
        actor_id
    )

    assert summary["total_amount"] == (
        Decimal("16.00")
    )

    assert summary["total_unpaid"] == (
        Decimal("16.00")
    )

    assert Fine.query.count() == 2

    assert Copy.query.count() == 1

    assert_financial_integrity()

    assert_reservation_integrity(
        library["book"].id
    )


# ==========================================
# RESERVATION CANCELLATION AFTER FINE
# ==========================================

def test_fine_reservation_cancellation(
    services,
    library,
    overdue_loan,
    waiting_reservation
):

    actor_id = library["librarian"].id

    loan = services["loan"].return_book(
        actor_id,
        overdue_loan.id
    )

    fine_id = loan.fine.id

    assert loan.copy.status == "RESERVED"

    services["reservation"].cancel_reservation(
        library["other_reader"].user_id,
        waiting_reservation.id
    )

    assert waiting_reservation.status == "CANCELLED"

    assert loan.copy.status == "AVAILABLE"

    fine = services["fine"].get_by_id(
        actor_id,
        fine_id
    )

    assert fine.amount == Decimal("6.00")

    assert fine.status == "UNPAID"

    assert Fine.query.count() == 1

    assert get_audit_count("FINE_CREATED") == 1

    assert_financial_integrity()

    assert_reservation_integrity(
        library["book"].id
    )


# ==========================================
# RESERVATION EXPIRATION AFTER FINE
# ==========================================

def test_fine_reservation_expiration(
    services,
    library,
    overdue_loan,
    waiting_reservation
):

    actor_id = library["librarian"].id

    loan = services["loan"].return_book(
        actor_id,
        overdue_loan.id
    )

    fine_id = loan.fine.id

    assert waiting_reservation.status == "READY"

    waiting_reservation.expires_at = (
        services["loan"].now()
        - timedelta(minutes=1)
    )

    db.session.commit()

    services["reservation"].expire_reservations(
        actor_id
    )

    assert waiting_reservation.status == "EXPIRED"

    assert loan.copy.status == "AVAILABLE"

    fine = services["fine"].get_by_id(
        actor_id,
        fine_id
    )

    assert fine.amount == Decimal("6.00")

    assert fine.status == "UNPAID"

    assert Fine.query.count() == 1

    assert_financial_integrity()

    assert_reservation_integrity(
        library["book"].id
    )


# ==========================================
# PAYMENTS DO NOT MODIFY RESERVATIONS
# ==========================================

@pytest.mark.parametrize(
    "amount, expected_status",
    [
        ("2.00", "PARTIALLY_PAID"),
        ("6.00", "PAID")
    ]
)
def test_fine_reservation_payment_independence(
    services,
    library,
    overdue_loan,
    waiting_reservation,
    amount,
    expected_status
):

    actor_id = library["librarian"].id

    loan = services["loan"].return_book(
        actor_id,
        overdue_loan.id
    )

    fine = loan.fine

    original_expiration = (
        waiting_reservation.expires_at
    )

    simulate_fine_payment(
        fine,
        amount,
        "CARD"
    )

    assert fine.status == expected_status

    assert waiting_reservation.status == "READY"

    assert waiting_reservation.expires_at == (
        original_expiration
    )

    assert loan.copy.status == "RESERVED"

    assert services["fine"].get_remaining_amount(
        actor_id,
        fine.id
    ) == Decimal("6.00") - Decimal(amount)

    assert_financial_integrity()

    assert_reservation_integrity(
        library["book"].id
    )


# ==========================================
# FINE OVERFLOW WITH WAITING RESERVATION
# ==========================================

def test_fine_reservation_overflow_rollback(
    services,
    library,
    overdue_loan,
    waiting_reservation
):

    actor_id = library["librarian"].id

    services["setting"].update(
        "FINE_PER_DAY",
        Decimal("99999999.99")
    )

    original_audit_count = AuditLog.query.count()

    with pytest.raises(
        BusinessRuleError,
        match="Calculated fine exceeds database limit"
    ):

        services["loan"].return_book(
            actor_id,
            overdue_loan.id
        )

    assert overdue_loan.status == "ACTIVE"

    assert overdue_loan.returned_at is None

    assert overdue_loan.copy.status == "LOANED"

    assert waiting_reservation.status == "WAITING"

    assert waiting_reservation.expires_at is None

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0

    assert AuditLog.query.count() == (
        original_audit_count
    )

    # Restore correct settings and retry.

    services["setting"].update(
        "FINE_PER_DAY",
        Decimal("1.00")
    )

    loan = services["loan"].return_book(
        actor_id,
        overdue_loan.id
    )

    assert loan.status == "RETURNED"

    assert loan.fine.amount == Decimal("6.00")

    assert waiting_reservation.status == "READY"

    assert loan.copy.status == "RESERVED"

    assert_financial_integrity()

    assert_reservation_integrity(
        library["book"].id
    )


# ==========================================
# ATOMIC RESERVATION AND FINE ROLLBACK
# ==========================================

def test_fine_reservation_assignment_rollback(
    services,
    library,
    overdue_loan,
    waiting_reservation,
    monkeypatch
):

    actor_id = library["librarian"].id

    loan_id = overdue_loan.id

    reservation_id = waiting_reservation.id

    copy_id = overdue_loan.copy_id

    book_id = library["book"].id

    original_audit_count = AuditLog.query.count()

    loan_service = services["loan"]

    original_log = loan_service.audit_service.log

    failure_calls = []

    def failing_log(action, *args, **kwargs):

        result = original_log(
            action,
            *args,
            **kwargs
        )

        if action == "LOAN_RETURNED":

            db.session.flush()

            assert Fine.query.count() == 1

            assert waiting_reservation.status == "READY"

            assert overdue_loan.copy.status == "RESERVED"

            failure_calls.append(True)

            raise RuntimeError(
                "Failure after reservation assignment"
            )

        return result

    with monkeypatch.context() as patch:

        patch.setattr(
            loan_service.audit_service,
            "log",
            failing_log
        )

        with pytest.raises(
            RuntimeError,
            match="Failure after reservation assignment"
        ):

            loan_service.return_book(
                actor_id,
                loan_id
            )

    assert failure_calls == [True]

    # Reload all records from the database.

    db.session.remove()

    loan = db.session.get(
        Loan,
        loan_id
    )

    reservation = db.session.get(
        Reservation,
        reservation_id
    )

    copy = db.session.get(
        Copy,
        copy_id
    )

    assert loan.status == "ACTIVE"

    assert loan.returned_at is None

    assert copy.status == "LOANED"

    assert reservation.status == "WAITING"

    assert reservation.expires_at is None

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0

    assert AuditLog.query.count() == (
        original_audit_count
    )

    assert_financial_integrity()

    assert_reservation_integrity(book_id)

    # Retry using a fresh service instance.

    fresh_service = LoanService()

    loan = fresh_service.return_book(
        actor_id,
        loan_id
    )

    assert loan.status == "RETURNED"

    assert loan.fine.amount == Decimal("6.00")

    assert reservation.status == "READY"

    assert copy.status == "RESERVED"

    assert Fine.query.count() == 1

    assert_financial_integrity()

    assert_reservation_integrity(book_id)


# ==========================================
# FINANCIAL AND RESERVATION AUDIT
# ==========================================

def test_fine_reservation_audit_integrity(
    services,
    library,
    overdue_loan,
    waiting_reservation
):

    actor_id = library["librarian"].id

    original_audit_ids = {
        audit.id
        for audit in AuditLog.query.all()
    }

    loan = services["loan"].return_book(
        actor_id,
        overdue_loan.id
    )

    fine = loan.fine

    audits = [
        audit
        for audit in AuditLog.query.all()
        if audit.id not in original_audit_ids
    ]

    fine_audits = [
        audit
        for audit in audits
        if audit.action == "FINE_CREATED"
    ]

    return_audits = [
        audit
        for audit in audits
        if audit.action == "LOAN_RETURNED"
    ]

    reservation_audits = [
        audit
        for audit in audits
        if audit.action == "RESERVATION_READY"
    ]

    assert len(fine_audits) == 1

    assert len(return_audits) == 1

    assert len(reservation_audits) == 1

    assert fine_audits[0].user_id == actor_id

    assert return_audits[0].user_id == actor_id

    assert reservation_audits[0].user_id == actor_id

    assert f"Fine ID: {fine.id}" in (
        fine_audits[0].description
    )

    assert f"Loan ID: {loan.id}" in (
        fine_audits[0].description
    )

    assert waiting_reservation.status == "READY"

    assert_financial_integrity()

    assert_reservation_integrity(
        library["book"].id
    )


# ==========================================
# READER FINANCIAL ISOLATION
# ==========================================

def test_fine_reservation_reader_isolation(
    services,
    library,
    overdue_loan,
    waiting_reservation
):

    actor_id = library["librarian"].id

    first_reader = library["reader"]

    second_reader = library["other_reader"]

    loan = services["loan"].return_book(
        actor_id,
        overdue_loan.id
    )

    fine = loan.fine

    assert services["fine"].get_own_total_unpaid(
        first_reader.user_id
    ) == Decimal("6.00")

    assert services["fine"].get_own_total_unpaid(
        second_reader.user_id
    ) == Decimal("0.00")

    with pytest.raises(AuthorizationError):

        services["fine"].get_by_id(
            second_reader.user_id,
            fine.id
        )

    with pytest.raises(AuthorizationError):

        services["fine"].get_remaining_amount(
            second_reader.user_id,
            fine.id
        )

    with pytest.raises(AuthorizationError):

        services["fine"].get_total_unpaid_by_reader(
            second_reader.user_id,
            first_reader.id
        )

    reservation = services["reservation"].get_by_id(
        second_reader.user_id,
        waiting_reservation.id
    )

    assert reservation.status == "READY"

    assert loan.copy.status == "RESERVED"

    assert_financial_integrity()

    assert_reservation_integrity(
        library["book"].id
    )


# ==========================================
# SECURITY AND FAILURE INTEGRATION TESTS
# ==========================================

from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import SQLAlchemyError


# ==========================================
# FINANCIAL RECORD OWNERSHIP
# ==========================================

@pytest.mark.parametrize(
    "method_name",
    [
        "get_by_id",
        "get_by_loan",
        "get_by_reader",
        "get_remaining_amount",
        "get_total_unpaid_by_reader",
        "get_reader_summary"
    ]
)
def test_fine_security_record_ownership(
    services,
    library,
    recorded_fine,
    method_name
):

    fine_service = services["fine"]

    owner = library["reader"]

    other_reader = library["other_reader"]

    arguments = {
        "get_by_id": recorded_fine.id,
        "get_by_loan": recorded_fine.loan_id,
        "get_by_reader": owner.id,
        "get_remaining_amount": recorded_fine.id,
        "get_total_unpaid_by_reader": owner.id,
        "get_reader_summary": owner.id
    }

    method = getattr(
        fine_service,
        method_name
    )

    original_audit_count = AuditLog.query.count()

    # The owner can access the financial record.

    result = method(
        owner.user_id,
        arguments[method_name]
    )

    assert result is not None

    # Another reader cannot access the same data.

    with pytest.raises(AuthorizationError):

        method(
            other_reader.user_id,
            arguments[method_name]
        )

    assert Fine.query.count() == 1

    assert Payment.query.count() == 0

    assert recorded_fine.status == "UNPAID"

    assert recorded_fine.amount == Decimal("6.00")

    assert AuditLog.query.count() == (
        original_audit_count
    )

    assert_financial_integrity()


# ==========================================
# GLOBAL FINANCIAL ACCESS PROTECTION
# ==========================================

@pytest.mark.parametrize(
    "method_name, arguments",
    [
        ("get_all", ()),
        ("get_by_status", ("UNPAID",)),
        ("get_unpaid_fines", ()),
        ("get_summary", ()),
        ("count", ())
    ]
)
def test_fine_security_global_access(
    services,
    library,
    recorded_fine,
    method_name,
    arguments
):

    method = getattr(
        services["fine"],
        method_name
    )

    for reader in library["readers"]:

        with pytest.raises(AuthorizationError):

            method(
                reader.user_id,
                *arguments
            )

    for actor_key in ["admin", "librarian"]:

        result = method(
            library[actor_key].id,
            *arguments
        )

        assert result is not None

    assert Fine.query.count() == 1

    assert_financial_integrity()


# ==========================================
# UNAUTHORIZED RETURN PROTECTION
# ==========================================

@pytest.mark.parametrize(
    "actor_key, expected_error",
    [
        ("reader", AuthorizationError),
        ("other_reader", AuthorizationError),
        (None, AuthenticationError)
    ]
)
def test_fine_security_unauthorized_return(
    services,
    library,
    overdue_loan,
    actor_key,
    expected_error
):

    actor_id = (
        library[actor_key].user_id
        if actor_key is not None
        else None
    )

    original_audit_count = AuditLog.query.count()

    with pytest.raises(expected_error):

        services["loan"].return_book(
            actor_id,
            overdue_loan.id
        )

    assert overdue_loan.status == "ACTIVE"

    assert overdue_loan.returned_at is None

    assert overdue_loan.copy.status == "LOANED"

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0

    assert AuditLog.query.count() == (
        original_audit_count
    )


# ==========================================
# INACTIVE STAFF ACCESS
# ==========================================

@pytest.mark.parametrize(
    "actor_key",
    ["admin", "librarian"]
)
def test_fine_security_inactive_staff(
    services,
    library,
    overdue_loan,
    actor_key
):

    actor = library[actor_key]

    actor.is_active = False

    db.session.commit()

    actor_id = actor.id

    original_audit_count = AuditLog.query.count()

    with pytest.raises(InactiveAccountError):

        services["loan"].return_book(
            actor_id,
            overdue_loan.id
        )

    with pytest.raises(InactiveAccountError):

        services["fine"].get_summary(
            actor_id
        )

    assert overdue_loan.status == "ACTIVE"

    assert overdue_loan.copy.status == "LOANED"

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0

    assert AuditLog.query.count() == (
        original_audit_count
    )


# ==========================================
# READER REACTIVATION
# ==========================================

def test_fine_security_reader_reactivation(
    services,
    library,
    recorded_fine
):

    admin_id = library["admin"].id

    reader = library["reader"]

    reader_user_id = reader.user_id

    fine_id = recorded_fine.id

    services["user"].deactivate_user(
        admin_id,
        reader_user_id
    )

    assert reader.user.is_active is False

    with pytest.raises(InactiveAccountError):

        services["fine"].get_own_summary(
            reader_user_id
        )

    # Staff can still access historical debts.

    assert services["fine"].get_remaining_amount(
        admin_id,
        fine_id
    ) == Decimal("6.00")

    services["user"].activate_user(
        admin_id,
        reader_user_id
    )

    assert reader.user.is_active is True

    assert services["fine"].get_own_total_unpaid(
        reader_user_id
    ) == Decimal("6.00")

    fines = services["fine"].get_own_fines(
        reader_user_id
    )

    assert len(fines) == 1

    assert fines[0].id == fine_id

    assert Fine.query.count() == 1

    assert get_audit_count("FINE_CREATED") == 1

    assert_financial_integrity()


# ==========================================
# DYNAMIC ROLE CHANGE
# ==========================================

def test_fine_security_dynamic_role_change(
    services,
    library,
    overdue_loan
):

    admin_id = library["admin"].id

    second_admin = services["user"].create_user(
        admin_id,
        "fine_security_admin",
        "security-admin@example.com",
        library["password"],
        role="ADMIN"
    )

    second_admin_id = second_admin.id

    assert services["auth"].require_admin(
        second_admin_id
    ).id == second_admin_id

    services["user"].change_role(
        admin_id,
        second_admin_id,
        "LIBRARIAN"
    )

    assert second_admin.role == "LIBRARIAN"

    with pytest.raises(AuthorizationError):

        services["auth"].require_admin(
            second_admin_id
        )

    # Cancelling loans requires administrator rights.

    with pytest.raises(AuthorizationError):

        services["loan"].cancel_loan(
            second_admin_id,
            overdue_loan.id,
            "Unauthorized cancellation"
        )

    assert overdue_loan.status == "ACTIVE"

    assert Fine.query.count() == 0

    # Returning books remains allowed for librarians.

    loan = services["loan"].return_book(
        second_admin_id,
        overdue_loan.id
    )

    assert loan.status == "RETURNED"

    assert loan.fine.amount == Decimal("6.00")

    audit = AuditLog.query.filter_by(
        action="FINE_CREATED"
    ).one()

    assert audit.user_id == second_admin_id

    assert_financial_integrity()


# ==========================================
# DUPLICATE RETURN PROTECTION
# ==========================================

def test_fine_security_duplicate_return(
    services,
    library,
    recorded_fine
):

    actor_id = library["librarian"].id

    loan_id = recorded_fine.loan_id

    fine_id = recorded_fine.id

    original_audit_count = AuditLog.query.count()

    for _ in range(3):

        with pytest.raises(
            LoanAlreadyReturnedError
        ):

            services["loan"].return_book(
                actor_id,
                loan_id
            )

    assert Loan.query.count() == 1

    assert Fine.query.count() == 1

    assert Payment.query.count() == 0

    assert AuditLog.query.count() == (
        original_audit_count
    )

    assert get_audit_count("FINE_CREATED") == 1

    fine = services["fine"].get_by_id(
        actor_id,
        fine_id
    )

    assert fine.amount == Decimal("6.00")

    assert fine.status == "UNPAID"

    assert_financial_integrity()


# ==========================================
# DATABASE UNIQUE CONSTRAINT
# ==========================================

def test_fine_security_database_duplicate(
    services,
    library,
    recorded_fine
):

    actor_id = library["admin"].id

    fine_id = recorded_fine.id

    loan_id = recorded_fine.loan_id

    duplicate = Fine(
        loan_id=loan_id,
        amount=Decimal("15.00"),
        paid_amount=Decimal("0.00"),
        status="UNPAID"
    )

    db.session.add(duplicate)

    try:

        with pytest.raises(IntegrityError):

            db.session.flush()

    finally:

        db.session.rollback()

    db.session.remove()

    assert Fine.query.count() == 1

    fine = services["fine"].get_by_id(
        actor_id,
        fine_id
    )

    assert fine.loan_id == loan_id

    assert fine.amount == Decimal("6.00")

    assert fine.status == "UNPAID"

    assert_financial_integrity()


# ==========================================
# FINANCIAL DATABASE CHECK CONSTRAINTS
# ==========================================

@pytest.mark.parametrize(
    "scenario",
    [
        "negative_fine",
        "excessive_paid_amount",
        "zero_payment",
        "negative_payment",
        "invalid_payment_method"
    ]
)
def test_fine_security_database_constraints(
    services,
    library,
    recorded_fine,
    scenario
):

    actor_id = library["admin"].id

    fine_id = recorded_fine.id

    original_audit_count = AuditLog.query.count()

    if scenario == "negative_fine":

        recorded_fine.amount = Decimal("-1.00")

    elif scenario == "excessive_paid_amount":

        recorded_fine.paid_amount = Decimal("7.00")

    elif scenario == "zero_payment":

        db.session.add(
            Payment(
                fine_id=fine_id,
                amount=Decimal("0.00"),
                method="CASH"
            )
        )

    elif scenario == "negative_payment":

        db.session.add(
            Payment(
                fine_id=fine_id,
                amount=Decimal("-1.00"),
                method="CASH"
            )
        )

    elif scenario == "invalid_payment_method":

        db.session.add(
            Payment(
                fine_id=fine_id,
                amount=Decimal("1.00"),
                method="UNKNOWN"
            )
        )

    try:

        with pytest.raises(IntegrityError):

            db.session.flush()

    finally:

        db.session.rollback()

    db.session.remove()

    fine = services["fine"].get_by_id(
        actor_id,
        fine_id
    )

    assert fine.amount == Decimal("6.00")

    assert fine.paid_amount == Decimal("0.00")

    assert fine.status == "UNPAID"

    assert Fine.query.count() == 1

    assert Payment.query.count() == 0

    assert AuditLog.query.count() == (
        original_audit_count
    )

    assert_financial_integrity()


# ==========================================
# AUDIT FAILURE WITH WAITING RESERVATION
# ==========================================

@pytest.mark.parametrize(
    "failure_action",
    [
        "FINE_CREATED",
        "LOAN_RETURNED"
    ]
)
def test_fine_security_audit_failure(
    services,
    library,
    overdue_loan,
    monkeypatch,
    failure_action
):

    actor_id = library["librarian"].id

    other_reader = library["other_reader"]

    loan_id = overdue_loan.id

    copy_id = overdue_loan.copy_id

    reservation = (
        services["reservation"].create_own_reservation(
            other_reader.user_id,
            library["book"].id
        )
    )

    reservation_id = reservation.id

    assert reservation.status == "WAITING"

    original_audit_count = AuditLog.query.count()

    loan_service = services["loan"]

    original_log = loan_service.audit_service.log

    failure_calls = []

    def failing_log(action, *args, **kwargs):

        result = original_log(
            action,
            *args,
            **kwargs
        )

        if action == failure_action:

            db.session.flush()

            assert Fine.query.count() == 1

            if action == "LOAN_RETURNED":

                assert reservation.status == "READY"

                assert overdue_loan.status == "RETURNED"

                assert overdue_loan.copy.status == (
                    "RESERVED"
                )

            failure_calls.append(action)

            raise SQLAlchemyError(
                "Simulated audit database failure"
            )

        return result

    with monkeypatch.context() as patch:

        patch.setattr(
            loan_service.audit_service,
            "log",
            failing_log
        )

        with pytest.raises(DatabaseError):

            loan_service.return_book(
                actor_id,
                loan_id
            )

    assert failure_calls == [failure_action]

    db.session.remove()

    loan = db.session.get(
        Loan,
        loan_id
    )

    copy = db.session.get(
        Copy,
        copy_id
    )

    reservation = db.session.get(
        Reservation,
        reservation_id
    )

    assert loan.status == "ACTIVE"

    assert loan.returned_at is None

    assert copy.status == "LOANED"

    assert reservation.status == "WAITING"

    assert reservation.expires_at is None

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0

    assert AuditLog.query.count() == (
        original_audit_count
    )

    assert_reservation_integrity(
        reservation.book_id
    )

    # Retry after restoring the audit service.

    fresh_loan_service = LoanService()

    loan = fresh_loan_service.return_book(
        actor_id,
        loan_id
    )

    assert loan.status == "RETURNED"

    assert loan.copy.status == "RESERVED"

    assert reservation.status == "READY"

    assert loan.fine.amount == Decimal("6.00")

    assert Fine.query.count() == 1

    assert get_audit_count("FINE_CREATED") == 1

    assert get_audit_count("LOAN_RETURNED") == 1

    assert_financial_integrity()

    assert_reservation_integrity(
        reservation.book_id
    )


# ==========================================
# FINANCIAL RECOVERY AFTER DATABASE FAILURE
# ==========================================

def test_fine_security_database_recovery(
    services,
    library,
    recorded_fine
):

    actor_id = library["admin"].id

    fine_id = recorded_fine.id

    original_summary = (
        services["fine"].get_summary(actor_id)
    )

    invalid_payment = Payment(
        fine_id=fine_id,
        amount=Decimal("-5.00"),
        method="CARD"
    )

    db.session.add(invalid_payment)

    recorded_fine.paid_amount = Decimal("2.00")

    recorded_fine.status = "PARTIALLY_PAID"

    try:

        with pytest.raises(IntegrityError):

            db.session.flush()

    finally:

        db.session.rollback()

    db.session.remove()

    fresh_service = FineService()

    assert fresh_service.get_summary(
        actor_id
    ) == original_summary

    fine = fresh_service.get_by_id(
        actor_id,
        fine_id
    )

    assert fine.paid_amount == Decimal("0.00")

    assert fine.status == "UNPAID"

    assert Payment.query.count() == 0

    # A valid simulated payment remains possible.

    simulate_fine_payment(
        fine,
        "2.00",
        "CARD"
    )

    assert fresh_service.get_remaining_amount(
        actor_id,
        fine_id
    ) == Decimal("4.00")

    assert fine.status == "PARTIALLY_PAID"

    assert Payment.query.count() == 1

    assert_financial_integrity()


# ==========================================
# UNKNOWN ACCOUNT PROTECTION
# ==========================================

@pytest.mark.parametrize(
    "method_name",
    [
        "get_by_id",
        "get_summary",
        "get_own_summary"
    ]
)
def test_fine_security_unknown_account(
    services,
    library,
    recorded_fine,
    method_name
):

    unknown_user_id = 999999

    assert db.session.get(
        User,
        unknown_user_id
    ) is None

    method = getattr(
        services["fine"],
        method_name
    )

    arguments = (
        (recorded_fine.id,)
        if method_name == "get_by_id"
        else ()
    )

    original_audit_count = AuditLog.query.count()

    with pytest.raises(AuthenticationError):

        method(
            unknown_user_id,
            *arguments
        )

    assert Fine.query.count() == 1

    assert Payment.query.count() == 0

    assert AuditLog.query.count() == (
        original_audit_count
    )

    assert_financial_integrity()