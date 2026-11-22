from datetime import timedelta
from decimal import Decimal

import pytest

from app.extensions import db

from app.models import (
    Payment,
    Fine,
    Loan
)

from app.repositories import PaymentRepository

from app.services import (
    AuthService,
    UserService,
    ReaderService,
    CategoryService,
    AuthorService,
    BookService,
    CopyService,
    LoanService,
    FineService
)

from app.models import User
from app.services import SettingService


# ==========================================
# REPOSITORY FIXTURE
# ==========================================

@pytest.fixture
def repository(app):

    return PaymentRepository()


# ==========================================
# TEST DATA FIXTURE
# ==========================================

@pytest.fixture
def payment_data(app):

    auth_service = AuthService()
    user_service = UserService()
    reader_service = ReaderService()
    category_service = CategoryService()
    author_service = AuthorService()
    book_service = BookService()
    copy_service = CopyService()
    loan_service = LoanService()
    fine_service = FineService()
    setting_service = SettingService()

    setting_service.initialize_defaults()

    password = "PaymentRepositoryPassword123!"

    admin = User(
        username="payment_repo_admin",
        email="admin@payment-repo.example.com",
        password_hash=auth_service.hash_password(
            password
        ),
        role="ADMIN",
        is_active=True
    )

    db.session.add(admin)
    db.session.commit()

    librarian = user_service.create_user(
        admin.id,
        "payment_repo_librarian",
        "librarian@payment-repo.example.com",
        password,
        role="LIBRARIAN"
    )

    actor_id = librarian.id

    readers = []

    for number in range(1, 4):

        reader = reader_service.register_reader(
            actor_id,
            f"payment_repo_reader{number}",
            f"reader{number}@payment-repo.example.com",
            password,
            "Jan",
            ["Kowalski", "Nowak", "Wisniewski"][number - 1]
        )

        readers.append(reader)

    category = category_service.create_category(
        actor_id,
        "Payment Repository Category",
        "Repository test category"
    )

    author = author_service.create_author(
        actor_id,
        "Jan",
        "Testowy"
    )

    book = book_service.create_book(
        actor_id,
        title="Payment repository test book",
        category_id=category.id,
        author_ids=[author.id]
    )

    fines = []

    # Reader 1 receives two fines.
    # Reader 2 receives one fine.
    # Reader 3 has no fines or payments.

    scenarios = [
        (readers[0], 20),
        (readers[0], 30),
        (readers[1], 50)
    ]

    for number, (reader, days) in enumerate(
        scenarios,
        start=1
    ):

        copy = copy_service.create_copy(
            actor_id,
            book.id,
            f"PAYMENT-REPO-{number:03d}"
        )

        loan = loan_service.borrow_book(
            actor_id,
            reader.id,
            copy.id
        )

        now = loan_service.now()

        loan.due_date = now - timedelta(
            days=days - 1,
            hours=12
        )

        loan.borrowed_at = (
            loan.due_date
            - timedelta(
                days=setting_service.get_loan_days()
            )
        )

        db.session.commit()

        loan = loan_service.return_book(
            actor_id,
            loan.id
        )

        fine = fine_service.get_by_loan(
            actor_id,
            loan.id
        )

        assert fine is not None

        assert fine.amount == Decimal(days)

        fines.append(fine)

    # PaymentService does not exist yet.
    # Payments are inserted directly as test data.

    payment_specs = [
        (fines[0], "10.00", "CASH"),
        (fines[0], "5.00", "CARD"),
        (fines[1], "20.00", "CARD"),
        (fines[2], "15.00", "CASH"),
        (fines[2], "25.00", "CARD")
    ]

    payments = []

    now = loan_service.now()

    for number, (fine, amount, method) in enumerate(
        payment_specs
    ):

        amount = Decimal(amount)

        payment = Payment(
            fine_id=fine.id,
            amount=amount,
            method=method,
            paid_at=now + timedelta(seconds=number)
        )

        db.session.add(payment)

        fine.paid_amount += amount

        fine.status = (
            "PAID"
            if fine.paid_amount == fine.amount
            else "PARTIALLY_PAID"
        )

        payments.append(payment)

    db.session.commit()

    return {
        "readers": readers,
        "fines": fines,
        "payments": payments,
        "actor_id": actor_id
    }


# ==========================================
# REPOSITORY INITIALIZATION
# ==========================================

def test_payment_repository_initialization(
    repository
):

    assert isinstance(
        repository,
        PaymentRepository
    )

    assert repository.model is Payment


# ==========================================
# PAYMENTS BY READER
# ==========================================

@pytest.mark.parametrize(
    "reader_index, expected_count",
    [
        (0, 3),
        (1, 2),
        (2, 0)
    ]
)
def test_payment_repository_get_by_reader(
    repository,
    payment_data,
    reader_index,
    expected_count
):

    reader = payment_data["readers"][reader_index]

    payments = repository.get_by_reader(
        reader.id
    )

    assert len(payments) == expected_count

    for payment in payments:

        assert payment.fine.loan.reader_id == reader.id


# ==========================================
# TOTAL PAYMENTS BY READER
# ==========================================

@pytest.mark.parametrize(
    "reader_index, expected_total",
    [
        (0, "35.00"),
        (1, "40.00"),
        (2, "0.00")
    ]
)
def test_payment_repository_get_total_by_reader(
    repository,
    payment_data,
    reader_index,
    expected_total
):

    reader = payment_data["readers"][reader_index]

    total = repository.get_total_by_reader(
        reader.id
    )

    assert isinstance(total, Decimal)

    assert total == Decimal(expected_total)


# ==========================================
# UNKNOWN READER
# ==========================================

def test_payment_repository_unknown_reader(
    repository,
    payment_data
):

    assert repository.get_by_reader(
        999999
    ) == []

    assert repository.get_total_by_reader(
        999999
    ) == Decimal("0.00")


# ==========================================
# DETERMINISTIC READER PAYMENT ORDER
# ==========================================

def test_payment_repository_reader_order(
    repository,
    payment_data
):

    reader = payment_data["readers"][0]

    payments = repository.get_by_reader(
        reader.id
    )

    actual_order = [
        (payment.paid_at, payment.id)
        for payment in payments
    ]

    assert actual_order == sorted(actual_order)


# ==========================================
# IDENTICAL PAYMENT TIMESTAMPS
# ==========================================

def test_payment_repository_equal_timestamps(
    repository,
    payment_data
):

    payments = payment_data["payments"][:3]

    timestamp = payments[0].paid_at

    for payment in payments:

        payment.paid_at = timestamp

    db.session.commit()

    reader = payment_data["readers"][0]

    results = repository.get_by_reader(
        reader.id
    )

    result_ids = [
        payment.id
        for payment in results
    ]

    assert result_ids == sorted(result_ids)

    assert len(result_ids) == 3


# ==========================================
# PAYMENT TOTAL CONSISTENCY
# ==========================================

def test_payment_repository_reader_totals(
    repository,
    payment_data
):

    total = Decimal("0.00")

    for reader in payment_data["readers"]:

        total += repository.get_total_by_reader(
            reader.id
        )

    assert total == Decimal("75.00")

    assert total == repository.get_total_payments()


# ==========================================
# PAYMENT HISTORY ISOLATION
# ==========================================

def test_payment_repository_reader_isolation(
    repository,
    payment_data
):

    first_reader = payment_data["readers"][0]
    second_reader = payment_data["readers"][1]

    first_ids = {
        payment.id
        for payment in repository.get_by_reader(
            first_reader.id
        )
    }

    second_ids = {
        payment.id
        for payment in repository.get_by_reader(
            second_reader.id
        )
    }

    assert len(first_ids) == 3

    assert len(second_ids) == 2

    assert first_ids.isdisjoint(second_ids)


# ==========================================
# EXISTING METHODS REGRESSION
# ==========================================

@pytest.mark.parametrize(
    "fine_index, expected_count, expected_total",
    [
        (0, 2, "15.00"),
        (1, 1, "20.00"),
        (2, 2, "40.00")
    ]
)
def test_payment_repository_fine_regression(
    repository,
    payment_data,
    fine_index,
    expected_count,
    expected_total
):

    fine = payment_data["fines"][fine_index]

    payments = repository.get_by_fine(
        fine.id
    )

    assert len(payments) == expected_count

    assert repository.get_total_by_fine(
        fine.id
    ) == Decimal(expected_total)


@pytest.mark.parametrize(
    "method, expected_count, expected_total",
    [
        ("CASH", 2, "25.00"),
        ("CARD", 3, "50.00")
    ]
)
def test_payment_repository_method_regression(
    repository,
    payment_data,
    method,
    expected_count,
    expected_total
):

    payments = repository.get_by_method(method)

    assert len(payments) == expected_count

    assert all(
        payment.method == method
        for payment in payments
    )

    total = sum(
        (payment.amount for payment in payments),
        Decimal("0.00")
    )

    assert total == Decimal(expected_total)


# ==========================================
# EMPTY DATABASE
# ==========================================

def test_payment_repository_empty_database(
    repository
):

    assert repository.get_by_reader(1) == []

    assert repository.get_total_by_reader(
        1
    ) == Decimal("0.00")

    assert repository.get_total_payments() == (
        Decimal("0.00")
    )

    assert repository.count() == 0


# ==========================================
# READ OPERATIONS DO NOT MODIFY FINANCIAL DATA
# ==========================================

def test_payment_repository_read_only(
    repository,
    payment_data
):

    original_fines = {
        fine.id: (
            fine.amount,
            fine.paid_amount,
            fine.status
        )
        for fine in Fine.query.all()
    }

    original_payments = Payment.query.count()

    original_loans = Loan.query.count()

    for reader in payment_data["readers"]:

        repository.get_by_reader(reader.id)

        repository.get_total_by_reader(reader.id)

    current_fines = {
        fine.id: (
            fine.amount,
            fine.paid_amount,
            fine.status
        )
        for fine in Fine.query.all()
    }

    assert current_fines == original_fines

    assert Payment.query.count() == original_payments

    assert Loan.query.count() == original_loans


# ==========================================
# ATOMIC FINE PAYMENT STATE TESTS
# ==========================================

from sqlalchemy.exc import IntegrityError
from app.repositories import FineRepository


@pytest.fixture
def fine_repository(app):

    return FineRepository()


# ==========================================
# SUCCESSFUL ATOMIC UPDATE
# ==========================================

@pytest.mark.parametrize(
    "new_paid_amount, new_status",
    [
        ("16.00", "PARTIALLY_PAID"),
        ("19.99", "PARTIALLY_PAID"),
        ("20.00", "PAID")
    ]
)
def test_fine_atomic_update_success(
    fine_repository,
    payment_data,
    new_paid_amount,
    new_status
):

    fine = payment_data["fines"][0]

    assert fine.amount == Decimal("20.00")

    assert fine.paid_amount == Decimal("15.00")

    assert fine.status == "PARTIALLY_PAID"

    result = fine_repository.update_payment_state(
        fine_id=fine.id,
        expected_amount=Decimal("20.00"),
        expected_paid_amount=Decimal("15.00"),
        expected_status="PARTIALLY_PAID",
        new_paid_amount=Decimal(new_paid_amount),
        new_status=new_status
    )

    assert result is True

    db.session.refresh(fine)

    assert fine.amount == Decimal("20.00")

    assert fine.paid_amount == Decimal(
        new_paid_amount
    )

    assert fine.status == new_status

    # The repository does not register payments
    # or commit the transaction.

    assert Payment.query.count() == 5

    db.session.rollback()

    db.session.refresh(fine)

    assert fine.paid_amount == Decimal("15.00")

    assert fine.status == "PARTIALLY_PAID"


# ==========================================
# REJECTION OF STALE FINANCIAL STATE
# ==========================================

@pytest.mark.parametrize(
    "expected_amount, expected_paid_amount, expected_status",
    [
        (
            "21.00",
            "15.00",
            "PARTIALLY_PAID"
        ),
        (
            "20.00",
            "14.00",
            "PARTIALLY_PAID"
        ),
        (
            "20.00",
            "15.00",
            "UNPAID"
        )
    ]
)
def test_fine_atomic_update_stale_state(
    fine_repository,
    payment_data,
    expected_amount,
    expected_paid_amount,
    expected_status
):

    fine = payment_data["fines"][0]

    result = fine_repository.update_payment_state(
        fine_id=fine.id,
        expected_amount=Decimal(expected_amount),
        expected_paid_amount=Decimal(
            expected_paid_amount
        ),
        expected_status=expected_status,
        new_paid_amount=Decimal("20.00"),
        new_status="PAID"
    )

    assert result is False

    db.session.refresh(fine)

    assert fine.amount == Decimal("20.00")

    assert fine.paid_amount == Decimal("15.00")

    assert fine.status == "PARTIALLY_PAID"

    assert Payment.query.count() == 5


# ==========================================
# UNKNOWN FINE
# ==========================================

def test_fine_atomic_update_unknown_fine(
    fine_repository,
    payment_data
):

    original_count = Fine.query.count()

    assert db.session.get(Fine, 999999) is None

    result = fine_repository.update_payment_state(
        fine_id=999999,
        expected_amount=Decimal("20.00"),
        expected_paid_amount=Decimal("0.00"),
        expected_status="UNPAID",
        new_paid_amount=Decimal("10.00"),
        new_status="PARTIALLY_PAID"
    )

    assert result is False

    assert Fine.query.count() == original_count

    assert Payment.query.count() == 5


# ==========================================
# SEQUENTIAL STALE SNAPSHOT PROTECTION
# ==========================================

def test_fine_atomic_update_stale_snapshot(
    fine_repository,
    payment_data
):

    fine = payment_data["fines"][0]

    actor_id = payment_data["actor_id"]

    fine_id = fine.id

    # Simulate two workers reading the same state.

    snapshot = {
        "expected_amount": fine.amount,
        "expected_paid_amount": fine.paid_amount,
        "expected_status": fine.status
    }

    assert snapshot["expected_paid_amount"] == (
        Decimal("15.00")
    )

    # First operation adds a valid payment of 3 PLN.

    first_result = (
        fine_repository.update_payment_state(
            fine_id=fine_id,
            **snapshot,
            new_paid_amount=Decimal("18.00"),
            new_status="PARTIALLY_PAID"
        )
    )

    assert first_result is True

    db.session.add(
        Payment(
            fine_id=fine_id,
            amount=Decimal("3.00"),
            method="CASH"
        )
    )

    db.session.commit()

    # Second operation still uses the old snapshot.

    second_result = (
        fine_repository.update_payment_state(
            fine_id=fine_id,
            **snapshot,
            new_paid_amount=Decimal("19.00"),
            new_status="PARTIALLY_PAID"
        )
    )

    assert second_result is False

    db.session.rollback()

    db.session.refresh(fine)

    assert fine.amount == Decimal("20.00")

    assert fine.paid_amount == Decimal("18.00")

    assert fine.status == "PARTIALLY_PAID"

    assert Payment.query.count() == 6

    fine_service = FineService()

    assert fine_service.get_remaining_amount(
        actor_id,
        fine_id
    ) == Decimal("2.00")


# ==========================================
# DATABASE CONSTRAINT PROTECTION
# ==========================================

@pytest.mark.parametrize(
    "new_paid_amount, new_status",
    [
        ("20.01", "PAID"),
        ("-1.00", "UNPAID"),
        ("18.00", "INVALID")
    ]
)
def test_fine_atomic_update_constraints(
    fine_repository,
    payment_data,
    new_paid_amount,
    new_status
):

    fine = payment_data["fines"][0]

    fine_id = fine.id

    try:

        with pytest.raises(IntegrityError):

            fine_repository.update_payment_state(
                fine_id=fine_id,
                expected_amount=Decimal("20.00"),
                expected_paid_amount=Decimal("15.00"),
                expected_status="PARTIALLY_PAID",
                new_paid_amount=Decimal(
                    new_paid_amount
                ),
                new_status=new_status
            )

    finally:

        db.session.rollback()

    db.session.refresh(fine)

    assert fine.amount == Decimal("20.00")

    assert fine.paid_amount == Decimal("15.00")

    assert fine.status == "PARTIALLY_PAID"

    assert Payment.query.count() == 5


# ==========================================
# ATOMIC UPDATE WITH PAYMENT ROLLBACK
# ==========================================

def test_fine_atomic_update_payment_rollback(
    fine_repository,
    payment_data
):

    fine = payment_data["fines"][0]

    fine_id = fine.id

    actor_id = payment_data["actor_id"]

    original_payment_count = Payment.query.count()

    result = fine_repository.update_payment_state(
        fine_id=fine_id,
        expected_amount=Decimal("20.00"),
        expected_paid_amount=Decimal("15.00"),
        expected_status="PARTIALLY_PAID",
        new_paid_amount=Decimal("20.00"),
        new_status="PAID"
    )

    assert result is True

    db.session.add(
        Payment(
            fine_id=fine_id,
            amount=Decimal("5.00"),
            method="CARD"
        )
    )

    db.session.flush()

    db.session.refresh(fine)

    assert fine.paid_amount == Decimal("20.00")

    assert fine.status == "PAID"

    assert Payment.query.count() == (
        original_payment_count + 1
    )

    # Roll back the entire operation.

    db.session.rollback()

    db.session.remove()

    fine = db.session.get(
        Fine,
        fine_id
    )

    assert fine.amount == Decimal("20.00")

    assert fine.paid_amount == Decimal("15.00")

    assert fine.status == "PARTIALLY_PAID"

    assert Payment.query.count() == (
        original_payment_count
    )

    fine_service = FineService()

    assert fine_service.get_remaining_amount(
        actor_id,
        fine_id
    ) == Decimal("5.00")