from datetime import timedelta
from decimal import Decimal

import pytest

from app.extensions import db

from app.models import (
    User,
    Reader,
    Book,
    Copy,
    Loan,
    Fine,
    Payment,
    AuditLog
)

from app.services import (
    FineService,
    LoanService,
    CopyService,
    SettingService
)

from app.exceptions import (
    ValidationError,
    BusinessRuleError,
    NotFoundError,
    AuthenticationError,
    AuthorizationError,
    InactiveAccountError,
    DatabaseError
)


# ==========================================
# SERVICE FIXTURES
# ==========================================

@pytest.fixture
def service(app):

    return FineService()


@pytest.fixture
def loan_service(app):

    return LoanService()


@pytest.fixture
def copy_service(app):

    return CopyService()


@pytest.fixture
def setting_service(app):

    return SettingService()


# ==========================================
# LIBRARY DATA FIXTURE
# ==========================================

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

    for number in range(1, 4):

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
        users,
        start=1
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

    for number in range(1, 4):

        book = Book(
            title=f"Fine test book {number}",
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


# ==========================================
# COPY FIXTURE
# ==========================================

@pytest.fixture
def copy(copy_service, data):

    return copy_service.create_copy(
        data["librarian"].id,
        data["book"].id,
        "FINE-INV-001"
    )


# ==========================================
# ACTIVE LOAN FIXTURE
# ==========================================

@pytest.fixture
def active_loan(
    loan_service,
    data,
    copy
):

    return loan_service.borrow_book(
        data["librarian"].id,
        data["reader"].id,
        copy.id
    )


# ==========================================
# OVERDUE LOAN FIXTURE
# ==========================================

@pytest.fixture
def overdue_loan(
    loan_service,
    active_loan
):

    now = loan_service.now()

    active_loan.borrowed_at = (
        now - timedelta(days=35, hours=12)
    )

    active_loan.due_date = (
        now - timedelta(days=5, hours=12)
    )

    db.session.commit()

    return active_loan


# ==========================================
# RETURNED LOAN WITH FINE
# ==========================================

@pytest.fixture
def unpaid_fine(
    loan_service,
    data,
    overdue_loan
):

    loan_service.return_book(
        data["librarian"].id,
        overdue_loan.id
    )

    return Fine.query.filter_by(
        loan_id=overdue_loan.id
    ).one()


# ==========================================
# PARTIALLY PAID FINE FIXTURE
# ==========================================

@pytest.fixture
def partially_paid_fine(unpaid_fine):

    payment = Payment(
        fine_id=unpaid_fine.id,
        amount=Decimal("2.00"),
        method="CASH"
    )

    db.session.add(payment)

    unpaid_fine.paid_amount = Decimal("2.00")
    unpaid_fine.status = "PARTIALLY_PAID"

    db.session.commit()

    return unpaid_fine


# ==========================================
# FULLY PAID FINE FIXTURE
# ==========================================

@pytest.fixture
def paid_fine(unpaid_fine):

    payment = Payment(
        fine_id=unpaid_fine.id,
        amount=unpaid_fine.amount,
        method="CARD"
    )

    db.session.add(payment)

    unpaid_fine.paid_amount = unpaid_fine.amount
    unpaid_fine.status = "PAID"

    db.session.commit()

    return unpaid_fine


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def get_audit_count(action):

    return AuditLog.query.filter_by(
        action=action
    ).count()


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
# INFRASTRUCTURE TESTS
# ==========================================

def test_fine_service_fixture(service):

    assert isinstance(
        service,
        FineService
    )

    assert service.repository is not None
    assert service.loan_repository is not None
    assert service.payment_repository is not None

    assert service.auth_service is not None
    assert service.audit_service is not None
    assert service.setting_service is not None


def test_fine_service_constants(service):

    assert service.VALID_STATUSES == (
        "UNPAID",
        "PARTIALLY_PAID",
        "PAID"
    )

    assert service.ZERO == Decimal("0.00")

    assert service.MONEY_PRECISION == (
        Decimal("0.01")
    )

    assert service.MAX_AMOUNT == (
        Decimal("99999999.99")
    )


def test_fine_data_fixture(data):

    assert data["admin"].role == "ADMIN"
    assert data["librarian"].role == "LIBRARIAN"

    assert len(data["readers"]) == 3
    assert len(data["books"]) == 3

    assert User.query.count() == 5
    assert Reader.query.count() == 3
    assert Book.query.count() == 3

    assert all(
        reader.user.is_active
        for reader in data["readers"]
    )


def test_fine_copy_fixture(data, copy):

    assert copy.id is not None

    assert copy.book_id == (
        data["book"].id
    )

    assert copy.status == "AVAILABLE"

    assert Copy.query.count() == 1


def test_fine_active_loan_fixture(
    data,
    copy,
    active_loan
):

    assert active_loan.id is not None

    assert active_loan.status == "ACTIVE"

    assert active_loan.reader_id == (
        data["reader"].id
    )

    assert active_loan.copy_id == copy.id

    assert copy.status == "LOANED"

    assert Fine.query.count() == 0


def test_fine_overdue_loan_fixture(
    data,
    loan_service,
    overdue_loan
):

    assert overdue_loan.status == "ACTIVE"

    assert loan_service.is_overdue(
        data["librarian"].id,
        overdue_loan.id
    ) is True

    assert loan_service.get_overdue_days(
        data["librarian"].id,
        overdue_loan.id
    ) == 6

    assert Fine.query.count() == 0


def test_fine_unpaid_fixture(
    service,
    data,
    unpaid_fine
):

    assert unpaid_fine.id is not None

    assert unpaid_fine.amount == (
        Decimal("6.00")
    )

    assert unpaid_fine.paid_amount == (
        Decimal("0.00")
    )

    assert unpaid_fine.status == "UNPAID"

    assert unpaid_fine.loan.status == "RETURNED"

    assert unpaid_fine.loan.copy.status == (
        "AVAILABLE"
    )

    assert Fine.query.count() == 1
    assert Payment.query.count() == 0

    assert service.get_remaining_amount(
        data["librarian"].id,
        unpaid_fine.id
    ) == Decimal("6.00")

    assert get_audit_count(
        "FINE_CREATED"
    ) == 1


def test_fine_partially_paid_fixture(
    service,
    data,
    partially_paid_fine
):

    fine = partially_paid_fine

    assert fine.amount == Decimal("6.00")

    assert fine.paid_amount == (
        Decimal("2.00")
    )

    assert fine.status == "PARTIALLY_PAID"

    assert Payment.query.count() == 1

    assert get_payment_total(
        fine.id
    ) == Decimal("2.00")

    assert service.get_remaining_amount(
        data["reader"].user_id,
        fine.id
    ) == Decimal("4.00")


def test_fine_paid_fixture(
    service,
    data,
    paid_fine
):

    assert paid_fine.amount == (
        Decimal("6.00")
    )

    assert paid_fine.paid_amount == (
        paid_fine.amount
    )

    assert paid_fine.status == "PAID"

    assert Payment.query.count() == 1

    assert get_payment_total(
        paid_fine.id
    ) == paid_fine.amount

    assert service.get_remaining_amount(
        data["reader"].user_id,
        paid_fine.id
    ) == Decimal("0.00")


def test_fine_default_settings(
    setting_service
):

    assert setting_service.get_fine_per_day() == (
        Decimal("1.00")
    )

    assert setting_service.get_loan_days() == 30

    assert setting_service.get_max_loans() == 5


def test_fine_loan_service_integration(
    loan_service
):

    assert isinstance(
        loan_service.fine_service,
        FineService
    )

    assert (
        loan_service.fine_service.repository
        is loan_service.fine_repository
    )

    assert (
        loan_service.fine_service.setting_service
        is loan_service.setting_service
    )

    assert (
        loan_service.fine_service.audit_service
        is loan_service.audit_service
    )

    assert (
        loan_service.fine_service.auth_service
        is loan_service.auth_service
    )


def test_fine_database_isolation(app):

    assert app.config["TESTING"] is True

    assert app.config[
        "SQLALCHEMY_DATABASE_URI"
    ] == "sqlite:///:memory:"

    assert User.query.count() == 0
    assert Reader.query.count() == 0
    assert Book.query.count() == 0
    assert Copy.query.count() == 0
    assert Loan.query.count() == 0
    assert Fine.query.count() == 0
    assert Payment.query.count() == 0
    assert AuditLog.query.count() == 0



# ==========================================
# IDENTIFIER VALIDATION
# ==========================================

@pytest.mark.parametrize(
    "value",
    [1, 10, 999999]
)
def test_validate_fine_id_valid(service, value):

    assert service.validate_id(
        value,
        "fine"
    ) == value


@pytest.mark.parametrize(
    "value",
    [
        0,
        -1,
        -100,
        None,
        True,
        False,
        "1",
        "",
        1.0,
        1.5,
        [],
        {},
        Decimal("1")
    ]
)
def test_validate_fine_id_invalid(service, value):

    with pytest.raises(
        ValidationError,
        match="Invalid fine identifier"
    ):

        service.validate_id(
            value,
            "fine"
        )


def test_validate_fine_id_field_name(service):

    with pytest.raises(
        ValidationError,
        match="Invalid loan identifier"
    ):

        service.validate_id(
            0,
            "loan"
        )


# ==========================================
# STATUS VALIDATION
# ==========================================

@pytest.mark.parametrize(
    "status",
    [
        "UNPAID",
        "PARTIALLY_PAID",
        "PAID"
    ]
)
def test_validate_fine_status_valid(service, status):

    assert service.validate_status(
        status
    ) == status


@pytest.mark.parametrize(
    "value, expected",
    [
        ("unpaid", "UNPAID"),
        ("partially_paid", "PARTIALLY_PAID"),
        ("paid", "PAID"),
        ("  UNPAID  ", "UNPAID"),
        (" Paid ", "PAID"),
        ("Partially_Paid", "PARTIALLY_PAID")
    ]
)
def test_validate_fine_status_normalization(
    service,
    value,
    expected
):

    assert service.validate_status(
        value
    ) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "ACTIVE",
        "CANCELLED",
        "RETURNED",
        "UNKNOWN",
        "PARTIALLY PAID",
        123,
        True,
        [],
        {}
    ]
)
def test_validate_fine_status_invalid(service, value):

    with pytest.raises(ValidationError):

        service.validate_status(value)


# ==========================================
# VALID MONETARY AMOUNTS
# ==========================================

@pytest.mark.parametrize(
    "value, expected",
    [
        (1, "1.00"),
        (100, "100.00"),
        ("1", "1.00"),
        ("15.50", "15.50"),
        ("0.01", "0.01"),
        ("10.1", "10.10"),
        ("10.00", "10.00"),
        (" 12.50 ", "12.50"),
        (Decimal("5.75"), "5.75"),
        (Decimal("0.10"), "0.10"),
        ("10.000", "10.00"),
        ("1e2", "100.00"),
        ("99999999.99", "99999999.99")
    ]
)
def test_validate_amount_valid(
    service,
    value,
    expected
):

    result = service.validate_amount(value)

    assert isinstance(result, Decimal)

    assert result == Decimal(expected)

    assert result.as_tuple().exponent == -2


# ==========================================
# ZERO AMOUNT VALIDATION
# ==========================================

@pytest.mark.parametrize(
    "value",
    [
        0,
        "0",
        "0.00",
        Decimal("0.00"),
        "-0.00"
    ]
)
def test_validate_amount_zero_allowed(
    service,
    value
):

    result = service.validate_amount(
        value,
        allow_zero=True
    )

    assert result == Decimal("0.00")

    assert result.as_tuple().exponent == -2

    assert result.is_signed() is False


@pytest.mark.parametrize(
    "value",
    [
        0,
        "0",
        "0.00",
        Decimal("0.00"),
        "-0.00"
    ]
)
def test_validate_amount_zero_forbidden(
    service,
    value
):

    with pytest.raises(ValidationError):

        service.validate_amount(
            value,
            allow_zero=False
        )


def test_validate_amount_positive_required(service):

    result = service.validate_amount(
        "0.01",
        allow_zero=False
    )

    assert result == Decimal("0.01")


# ==========================================
# NEGATIVE MONETARY AMOUNTS
# ==========================================

@pytest.mark.parametrize(
    "value",
    [
        -1,
        -100,
        "-0.01",
        "-15.50",
        Decimal("-0.01"),
        Decimal("-99999999.99")
    ]
)
def test_validate_amount_negative(
    service,
    value
):

    with pytest.raises(ValidationError):

        service.validate_amount(value)


# ==========================================
# MONETARY PRECISION
# ==========================================

@pytest.mark.parametrize(
    "value",
    [
        "0.001",
        "1.234",
        "10.999",
        "15.505",
        "99999999.991",
        Decimal("12.345"),
        Decimal("0.0001")
    ]
)
def test_validate_amount_excessive_precision(
    service,
    value
):

    with pytest.raises(ValidationError):

        service.validate_amount(value)


# ==========================================
# MONETARY LIMITS
# ==========================================

@pytest.mark.parametrize(
    "value",
    [
        100000000,
        "100000000.00",
        "99999999.999",
        Decimal("100000000.01"),
        "99999999999999999999999999",
        "1e100"
    ]
)
def test_validate_amount_exceeds_limit(
    service,
    value
):

    with pytest.raises(ValidationError):

        service.validate_amount(value)


def test_validate_amount_maximum_boundary(service):

    result = service.validate_amount(
        service.MAX_AMOUNT
    )

    assert result == Decimal("99999999.99")

    assert result.as_tuple().exponent == -2


# ==========================================
# NON-FINITE MONETARY VALUES
# ==========================================

@pytest.mark.parametrize(
    "value",
    [
        "NaN",
        "sNaN",
        "Infinity",
        "-Infinity",
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity")
    ]
)
def test_validate_amount_non_finite(
    service,
    value
):

    with pytest.raises(ValidationError):

        service.validate_amount(value)


# ==========================================
# INVALID MONETARY TYPES
# ==========================================

@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        1.0,
        10.50,
        float("nan"),
        float("inf"),
        [],
        {},
        (),
        b"10.00",
        complex(1, 2)
    ]
)
def test_validate_amount_invalid_type(
    service,
    value
):

    with pytest.raises(ValidationError):

        service.validate_amount(value)


# ==========================================
# INVALID MONETARY TEXT
# ==========================================

@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "abc",
        "10,50",
        "10 PLN",
        "10.00 zl",
        "12.34.56",
        "--1",
        "1 000.00"
    ]
)
def test_validate_amount_invalid_text(
    service,
    value
):

    with pytest.raises(ValidationError):

        service.validate_amount(value)


# ==========================================
# INVALID VALIDATION OPTIONS
# ==========================================

@pytest.mark.parametrize(
    "allow_zero",
    [
        None,
        0,
        1,
        "True",
        "False",
        [],
        {}
    ]
)
def test_validate_amount_invalid_option(
    service,
    allow_zero
):

    with pytest.raises(
        ValidationError,
        match="Invalid zero amount option"
    ):

        service.validate_amount(
            "10.00",
            allow_zero=allow_zero
        )


# ==========================================
# DECIMAL ACCURACY
# ==========================================

def test_validate_amount_decimal_accuracy(service):

    first = service.validate_amount("0.10")
    second = service.validate_amount("0.20")

    result = first + second

    assert result == Decimal("0.30")


def test_validate_amount_preserves_decimal_precision(
    service
):

    amount = Decimal("12345678.91")

    result = service.validate_amount(amount)

    assert result == amount

    assert isinstance(result, Decimal)

    assert result.as_tuple().exponent == -2


# ==========================================
# VALIDATION SIDE EFFECTS
# ==========================================

def test_fine_validation_has_no_database_side_effects(
    service,
    data
):

    audit_count = AuditLog.query.count()

    service.validate_id(1, "fine")

    service.validate_status("UNPAID")

    service.validate_amount("25.50")

    with pytest.raises(ValidationError):

        service.validate_amount("-1.00")

    with pytest.raises(ValidationError):

        service.validate_status("UNKNOWN")

    with pytest.raises(ValidationError):

        service.validate_id(0, "fine")

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0

    assert Loan.query.count() == 0

    assert AuditLog.query.count() == audit_count


# ==========================================
# AUTHORIZATION TEST CONFIGURATION
# ==========================================

FINE_SCOPED_METHODS = [
    "get_by_id",
    "get_by_loan",
    "get_by_reader",
    "get_remaining_amount",
    "get_total_unpaid_by_reader",
    "get_reader_summary"
]

FINE_STAFF_METHODS = [
    "get_all",
    "get_by_status",
    "get_unpaid_fines",
    "get_summary",
    "count"
]

FINE_OWN_METHODS = [
    "get_own_fines",
    "get_own_unpaid_fines",
    "get_own_total_unpaid",
    "get_own_summary"
]


def call_fine_method(
    service,
    method_name,
    actor_id,
    fine
):

    method = getattr(service, method_name)

    arguments = {
        "get_by_id": (fine.id,),
        "get_by_loan": (fine.loan_id,),
        "get_by_reader": (fine.loan.reader_id,),
        "get_remaining_amount": (fine.id,),
        "get_total_unpaid_by_reader": (
            fine.loan.reader_id,
        ),
        "get_reader_summary": (
            fine.loan.reader_id,
        ),
        "get_by_status": ("UNPAID",)
    }

    return method(
        actor_id,
        *arguments.get(method_name, ())
    )


def assert_fine_access_result(
    method_name,
    result,
    fine
):

    if method_name in (
        "get_by_id",
        "get_by_loan"
    ):

        assert result.id == fine.id

    elif method_name in (
        "get_by_reader",
        "get_all",
        "get_by_status",
        "get_unpaid_fines",
        "get_own_fines",
        "get_own_unpaid_fines"
    ):

        assert [
            item.id for item in result
        ] == [fine.id]

    elif method_name in (
        "get_remaining_amount",
        "get_total_unpaid_by_reader",
        "get_own_total_unpaid"
    ):

        assert result == Decimal("6.00")

        assert isinstance(result, Decimal)

    elif method_name in (
        "get_summary",
        "get_reader_summary",
        "get_own_summary"
    ):

        assert result["total_fines"] == 1

        assert result["unpaid_fines"] == 1

        assert result["partially_paid_fines"] == 0

        assert result["paid_fines"] == 0

        assert result["total_amount"] == (
            Decimal("6.00")
        )

        assert result["total_paid"] == (
            Decimal("0.00")
        )

        assert result["total_unpaid"] == (
            Decimal("6.00")
        )

        if method_name != "get_summary":

            assert result["reader_id"] == (
                fine.loan.reader_id
            )

    elif method_name == "count":

        assert result == 1

    else:

        pytest.fail(
            f"Unsupported test method: {method_name}"
        )


# ==========================================
# AUTHORIZED SCOPED ACCESS
# ==========================================

@pytest.mark.parametrize(
    "actor_key",
    ["admin", "librarian", "user"]
)
@pytest.mark.parametrize(
    "method_name",
    FINE_SCOPED_METHODS
)
def test_fine_authorized_scoped_access(
    service,
    data,
    unpaid_fine,
    actor_key,
    method_name
):

    actor = data[actor_key]

    result = call_fine_method(
        service,
        method_name,
        actor.id,
        unpaid_fine
    )

    assert_fine_access_result(
        method_name,
        result,
        unpaid_fine
    )


# ==========================================
# AUTHORIZED STAFF ACCESS
# ==========================================

@pytest.mark.parametrize(
    "actor_key",
    ["admin", "librarian"]
)
@pytest.mark.parametrize(
    "method_name",
    FINE_STAFF_METHODS
)
def test_fine_authorized_staff_access(
    service,
    data,
    unpaid_fine,
    actor_key,
    method_name
):

    actor = data[actor_key]

    result = call_fine_method(
        service,
        method_name,
        actor.id,
        unpaid_fine
    )

    assert_fine_access_result(
        method_name,
        result,
        unpaid_fine
    )


# ==========================================
# READER GLOBAL ACCESS RESTRICTIONS
# ==========================================

@pytest.mark.parametrize(
    "method_name",
    FINE_STAFF_METHODS
)
def test_fine_reader_global_access_denied(
    service,
    data,
    unpaid_fine,
    method_name
):

    actor = data["user"]

    with pytest.raises(AuthorizationError):

        call_fine_method(
            service,
            method_name,
            actor.id,
            unpaid_fine
        )


# ==========================================
# OTHER READER DATA PROTECTION
# ==========================================

@pytest.mark.parametrize(
    "method_name",
    FINE_SCOPED_METHODS
)
def test_fine_other_reader_access_denied(
    service,
    data,
    unpaid_fine,
    method_name
):

    actor = data["other_user"]

    with pytest.raises(AuthorizationError):

        call_fine_method(
            service,
            method_name,
            actor.id,
            unpaid_fine
        )


# ==========================================
# READER OWN PROFILE ACCESS
# ==========================================

@pytest.mark.parametrize(
    "method_name",
    FINE_OWN_METHODS
)
def test_fine_own_profile_access(
    service,
    data,
    unpaid_fine,
    method_name
):

    result = call_fine_method(
        service,
        method_name,
        data["user"].id,
        unpaid_fine
    )

    assert_fine_access_result(
        method_name,
        result,
        unpaid_fine
    )


# ==========================================
# STAFF READER PROFILE RESTRICTIONS
# ==========================================

@pytest.mark.parametrize(
    "actor_key",
    ["admin", "librarian"]
)
@pytest.mark.parametrize(
    "method_name",
    FINE_OWN_METHODS
)
def test_fine_staff_own_profile_denied(
    service,
    data,
    unpaid_fine,
    actor_key,
    method_name
):

    with pytest.raises(AuthorizationError):

        call_fine_method(
            service,
            method_name,
            data[actor_key].id,
            unpaid_fine
        )


# ==========================================
# UNAUTHENTICATED ACCESS
# ==========================================

@pytest.mark.parametrize(
    "method_name",
    (
        FINE_SCOPED_METHODS
        + FINE_STAFF_METHODS
        + FINE_OWN_METHODS
    )
)
def test_fine_unauthenticated_access(
    service,
    unpaid_fine,
    method_name
):

    with pytest.raises(AuthenticationError):

        call_fine_method(
            service,
            method_name,
            None,
            unpaid_fine
        )


# ==========================================
# INACTIVE ACCOUNT ACCESS
# ==========================================

@pytest.mark.parametrize(
    "method_name",
    (
        FINE_SCOPED_METHODS
        + FINE_STAFF_METHODS
        + FINE_OWN_METHODS
    )
)
def test_fine_inactive_account_access(
    service,
    data,
    unpaid_fine,
    method_name
):

    actor = data["user"]

    actor.is_active = False

    db.session.commit()

    with pytest.raises(InactiveAccountError):

        call_fine_method(
            service,
            method_name,
            actor.id,
            unpaid_fine
        )

    assert unpaid_fine.status == "UNPAID"

    assert unpaid_fine.amount == (
        Decimal("6.00")
    )

    assert unpaid_fine.paid_amount == (
        Decimal("0.00")
    )


# ==========================================
# NONEXISTENT RECORD PRIVACY
# ==========================================

@pytest.mark.parametrize(
    "actor_key",
    ["admin", "librarian", "user"]
)
@pytest.mark.parametrize(
    "method_name",
    ["get_by_id", "get_by_loan"]
)
def test_fine_nonexistent_record_privacy(
    service,
    data,
    actor_key,
    method_name
):

    actor = data[actor_key]

    method = getattr(service, method_name)

    expected_error = (
        AuthorizationError
        if actor.role == "READER"
        else NotFoundError
    )

    with pytest.raises(expected_error):

        method(
            actor.id,
            999999
        )


# ==========================================
# INVALID IDENTIFIER PUBLIC ACCESS
# ==========================================

@pytest.mark.parametrize(
    "method_name",
    FINE_SCOPED_METHODS
)
def test_fine_public_invalid_identifier(
    service,
    data,
    method_name
):

    method = getattr(service, method_name)

    with pytest.raises(ValidationError):

        method(
            data["admin"].id,
            0
        )


# ==========================================
# AUTHORIZATION SIDE EFFECTS
# ==========================================

def test_fine_authorization_has_no_side_effects(
    service,
    data,
    unpaid_fine
):

    audit_count = AuditLog.query.count()

    payment_count = Payment.query.count()

    fine_count = Fine.query.count()

    original_amount = unpaid_fine.amount

    original_paid_amount = (
        unpaid_fine.paid_amount
    )

    original_status = unpaid_fine.status

    # Authorized read operations.

    for method_name in FINE_SCOPED_METHODS:

        call_fine_method(
            service,
            method_name,
            data["user"].id,
            unpaid_fine
        )

    for method_name in FINE_STAFF_METHODS:

        call_fine_method(
            service,
            method_name,
            data["librarian"].id,
            unpaid_fine
        )

    for method_name in FINE_OWN_METHODS:

        call_fine_method(
            service,
            method_name,
            data["user"].id,
            unpaid_fine
        )

    # Unauthorized read operations.

    for method_name in FINE_SCOPED_METHODS:

        with pytest.raises(AuthorizationError):

            call_fine_method(
                service,
                method_name,
                data["other_user"].id,
                unpaid_fine
            )

    for method_name in FINE_STAFF_METHODS:

        with pytest.raises(AuthorizationError):

            call_fine_method(
                service,
                method_name,
                data["user"].id,
                unpaid_fine
            )

    # Verify that no financial data was changed.

    assert Fine.query.count() == fine_count

    assert Payment.query.count() == payment_count

    assert AuditLog.query.count() == audit_count

    assert unpaid_fine.amount == original_amount

    assert unpaid_fine.paid_amount == (
        original_paid_amount
    )

    assert unpaid_fine.status == original_status

    assert unpaid_fine.loan.status == "RETURNED"


# ==========================================
# DEFAULT FINE CALCULATION
# ==========================================

@pytest.mark.parametrize(
    "days, expected",
    [
        (0, "0.00"),
        (1, "1.00"),
        (5, "5.00"),
        (30, "30.00"),
        (365, "365.00"),
        (1000, "1000.00")
    ]
)
def test_calculate_fine_default_rate(
    service,
    days,
    expected
):

    result = service.calculate_fine_amount(days)

    assert result == Decimal(expected)

    assert isinstance(result, Decimal)

    assert result.as_tuple().exponent == -2


# ==========================================
# CUSTOM DAILY RATES
# ==========================================

@pytest.mark.parametrize(
    "rate, days, expected",
    [
        ("2.50", 5, "12.50"),
        ("0.25", 10, "2.50"),
        ("0.01", 1, "0.01"),
        ("0.10", 3, "0.30"),
        ("1.99", 7, "13.93"),
        ("15.75", 12, "189.00"),
        ("100.00", 0, "0.00")
    ]
)
def test_calculate_fine_custom_rate(
    service,
    setting_service,
    rate,
    days,
    expected
):

    setting_service.update(
        "FINE_PER_DAY",
        Decimal(rate)
    )

    result = service.calculate_fine_amount(days)

    assert result == Decimal(expected)

    assert isinstance(result, Decimal)

    assert result.as_tuple().exponent == -2


# ==========================================
# INVALID OVERDUE DAYS
# ==========================================

@pytest.mark.parametrize(
    "days",
    [
        -1,
        -100,
        None,
        True,
        False,
        "5",
        "",
        5.0,
        2.5,
        Decimal("5"),
        [],
        {}
    ]
)
def test_calculate_fine_invalid_days(
    service,
    days
):

    with pytest.raises(
        ValidationError,
        match="Overdue days must be a non-negative integer"
    ):

        service.calculate_fine_amount(days)


# ==========================================
# ZERO DAILY RATE
# ==========================================

@pytest.mark.parametrize(
    "days",
    [0, 1, 365, 10**100]
)
def test_calculate_fine_zero_rate(
    service,
    setting_service,
    days
):

    setting_service.update(
        "FINE_PER_DAY",
        Decimal("0.00")
    )

    result = service.calculate_fine_amount(days)

    assert result == Decimal("0.00")

    assert result.as_tuple().exponent == -2


# ==========================================
# MAXIMUM ALLOWED FINE
# ==========================================

@pytest.mark.parametrize(
    "rate, days, expected",
    [
        ("99999999.99", 1, "99999999.99"),
        ("0.01", 9999999999, "99999999.99"),
        ("1.00", 99999999, "99999999.00"),
        ("0.03", 3333333333, "99999999.99")
    ]
)
def test_calculate_fine_maximum_boundary(
    service,
    setting_service,
    rate,
    days,
    expected
):

    setting_service.update(
        "FINE_PER_DAY",
        Decimal(rate)
    )

    result = service.calculate_fine_amount(days)

    assert result == Decimal(expected)

    assert result <= service.MAX_AMOUNT

    assert result.as_tuple().exponent == -2


# ==========================================
# FINANCIAL OVERFLOW PROTECTION
# ==========================================

@pytest.mark.parametrize(
    "rate, days",
    [
        ("99999999.99", 2),
        ("0.01", 10000000000),
        ("1.00", 100000000),
        ("1.00", 10**100)
    ]
)
def test_calculate_fine_exceeds_database_limit(
    service,
    setting_service,
    rate,
    days
):

    setting_service.update(
        "FINE_PER_DAY",
        Decimal(rate)
    )

    with pytest.raises(
        BusinessRuleError,
        match="Calculated fine exceeds database limit"
    ):

        service.calculate_fine_amount(days)


# ==========================================
# DYNAMIC DAILY RATE
# ==========================================

def test_calculate_fine_dynamic_rate(
    service,
    setting_service
):

    assert service.calculate_fine_amount(
        10
    ) == Decimal("10.00")

    setting_service.update(
        "FINE_PER_DAY",
        Decimal("2.50")
    )

    assert service.calculate_fine_amount(
        10
    ) == Decimal("25.00")

    setting_service.update(
        "FINE_PER_DAY",
        Decimal("0.00")
    )

    assert service.calculate_fine_amount(
        10
    ) == Decimal("0.00")

    setting_service.reset_to_defaults()

    assert service.calculate_fine_amount(
        10
    ) == Decimal("10.00")


# ==========================================
# ACTIVE LOAN FINE ESTIMATION
# ==========================================

def test_calculate_active_loan_fine_estimation(
    service,
    loan_service,
    setting_service,
    data,
    overdue_loan
):

    librarian = data["librarian"]

    reader = data["reader"]

    setting_service.update(
        "FINE_PER_DAY",
        Decimal("2.50")
    )

    days = loan_service.get_overdue_days(
        librarian.id,
        overdue_loan.id
    )

    assert days == 6

    expected = service.calculate_fine_amount(days)

    staff_estimation = loan_service.calculate_fine(
        librarian.id,
        overdue_loan.id
    )

    reader_estimation = loan_service.calculate_fine(
        reader.user_id,
        overdue_loan.id
    )

    assert expected == Decimal("15.00")

    assert staff_estimation == expected

    assert reader_estimation == expected

    # Estimating a fine must not create a record.

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0

    assert overdue_loan.status == "ACTIVE"

    assert get_audit_count("FINE_CREATED") == 0


# ==========================================
# HISTORICAL FINE AMOUNT PROTECTION
# ==========================================

def test_calculate_existing_fine_after_rate_change(
    service,
    loan_service,
    setting_service,
    data,
    unpaid_fine
):

    librarian = data["librarian"]

    original_amount = unpaid_fine.amount

    original_fine_id = unpaid_fine.id

    assert original_amount == Decimal("6.00")

    setting_service.update(
        "FINE_PER_DAY",
        Decimal("5.00")
    )

    # New calculations use the new daily rate.

    assert service.calculate_fine_amount(
        6
    ) == Decimal("30.00")

    # Previously recorded fines remain unchanged.

    assert loan_service.calculate_fine(
        librarian.id,
        unpaid_fine.loan_id
    ) == original_amount

    assert service.get_remaining_amount(
        librarian.id,
        unpaid_fine.id
    ) == original_amount

    fine = service.get_by_id(
        librarian.id,
        original_fine_id
    )

    assert fine.amount == original_amount

    assert fine.status == "UNPAID"

    assert Fine.query.count() == 1

    assert get_audit_count("FINE_CREATED") == 1


# ==========================================
# RETURNED LOAN WITHOUT FINE
# ==========================================

def test_calculate_returned_loan_without_fine(
    service,
    loan_service,
    setting_service,
    data,
    active_loan
):

    librarian = data["librarian"]

    loan = loan_service.return_book(
        librarian.id,
        active_loan.id
    )

    assert loan.status == "RETURNED"

    assert service.get_by_loan(
        librarian.id,
        loan.id
    ) is None

    setting_service.update(
        "FINE_PER_DAY",
        Decimal("10.00")
    )

    result = loan_service.calculate_fine(
        librarian.id,
        loan.id
    )

    assert result == Decimal("0.00")

    assert Fine.query.count() == 0

    assert get_audit_count("FINE_CREATED") == 0


# ==========================================
# CANCELLED LOAN FINE CALCULATION
# ==========================================

def test_calculate_cancelled_loan_fine(
    service,
    loan_service,
    data,
    active_loan
):

    admin = data["admin"]

    loan = loan_service.cancel_loan(
        admin.id,
        active_loan.id,
        "Test loan cancellation"
    )

    assert loan.status == "CANCELLED"

    result = loan_service.calculate_fine(
        admin.id,
        loan.id
    )

    assert result == Decimal("0.00")

    assert service.get_by_loan(
        admin.id,
        loan.id
    ) is None

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0

    assert get_audit_count("FINE_CREATED") == 0


# ==========================================
# CALCULATION SIDE EFFECTS
# ==========================================

def test_calculate_fine_has_no_side_effects(
    service,
    setting_service,
    data
):

    setting_service.update(
        "FINE_PER_DAY",
        Decimal("2.50")
    )

    original_audit_count = AuditLog.query.count()

    original_settings = setting_service.get_all()

    for days in [0, 1, 5, 10, 30, 365]:

        result = service.calculate_fine_amount(days)

        assert result == (
            Decimal(days) * Decimal("2.50")
        ).quantize(Decimal("0.01"))

    with pytest.raises(ValidationError):

        service.calculate_fine_amount(-1)

    with pytest.raises(BusinessRuleError):

        service.calculate_fine_amount(10**100)

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0

    assert Loan.query.count() == 0

    assert AuditLog.query.count() == (
        original_audit_count
    )

    assert setting_service.get_all() == (
        original_settings
    )


# ==========================================
# RETURN DEADLINE BOUNDARIES
# ==========================================

@pytest.mark.parametrize(
    "seconds, expected_amount",
    [
        (-1, "0.00"),
        (0, "0.00"),
        (1, "1.00"),
        (86400, "1.00"),
        (86401, "2.00"),
        (172800, "2.00"),
        (172801, "3.00")
    ]
)
def test_return_fine_deadline_boundaries(
    service,
    loan_service,
    data,
    active_loan,
    monkeypatch,
    seconds,
    expected_amount
):

    returned_at = (
        active_loan.due_date
        + timedelta(seconds=seconds)
    )

    monkeypatch.setattr(
        loan_service,
        "now",
        lambda: returned_at
    )

    actor_id = data["librarian"].id

    loan = loan_service.return_book(
        actor_id,
        active_loan.id
    )

    expected = Decimal(expected_amount)

    assert loan.status == "RETURNED"
    assert loan.returned_at == returned_at
    assert loan.copy.status == "AVAILABLE"

    fine = service.get_by_loan(
        actor_id,
        loan.id
    )

    if expected == Decimal("0.00"):

        assert fine is None

        assert Fine.query.count() == 0

        assert get_audit_count(
            "FINE_CREATED"
        ) == 0

    else:

        assert fine is not None

        assert fine.loan_id == loan.id

        assert fine.amount == expected

        assert fine.paid_amount == (
            Decimal("0.00")
        )

        assert fine.status == "UNPAID"

        assert Fine.query.count() == 1

        assert get_audit_count(
            "FINE_CREATED"
        ) == 1

    assert Payment.query.count() == 0

    assert get_audit_count(
        "LOAN_RETURNED"
    ) == 1


# ==========================================
# CUSTOM FINE RATES DURING RETURN
# ==========================================

@pytest.mark.parametrize(
    "rate, expected",
    [
        ("0.00", "0.00"),
        ("0.25", "1.50"),
        ("2.50", "15.00")
    ]
)
def test_return_fine_custom_daily_rate(
    service,
    loan_service,
    setting_service,
    data,
    overdue_loan,
    monkeypatch,
    rate,
    expected
):

    setting_service.update(
        "FINE_PER_DAY",
        Decimal(rate)
    )

    returned_at = (
        overdue_loan.due_date
        + timedelta(days=5, hours=12)
    )

    monkeypatch.setattr(
        loan_service,
        "now",
        lambda: returned_at
    )

    actor_id = data["librarian"].id

    loan = loan_service.return_book(
        actor_id,
        overdue_loan.id
    )

    fine = service.get_by_loan(
        actor_id,
        loan.id
    )

    expected_amount = Decimal(expected)

    assert loan.status == "RETURNED"

    assert loan.copy.status == "AVAILABLE"

    if expected_amount == Decimal("0.00"):

        assert fine is None

        assert Fine.query.count() == 0

        assert get_audit_count(
            "FINE_CREATED"
        ) == 0

    else:

        assert fine.amount == expected_amount

        assert fine.paid_amount == (
            Decimal("0.00")
        )

        assert fine.status == "UNPAID"

        assert Fine.query.count() == 1

        assert get_audit_count(
            "FINE_CREATED"
        ) == 1

    assert Payment.query.count() == 0


# ==========================================
# FINE CREATION BY STAFF
# ==========================================

@pytest.mark.parametrize(
    "actor_key",
    ["admin", "librarian"]
)
def test_return_fine_staff_creation(
    service,
    loan_service,
    data,
    overdue_loan,
    actor_key
):

    actor = data[actor_key]

    loan = loan_service.return_book(
        actor.id,
        overdue_loan.id
    )

    fine = service.get_by_loan(
        actor.id,
        loan.id
    )

    assert fine is not None

    assert fine.amount == Decimal("6.00")

    assert fine.status == "UNPAID"

    assert fine.created_at is not None

    assert fine.created_at.tzinfo is None

    audit = AuditLog.query.filter_by(
        action="FINE_CREATED"
    ).one()

    assert audit.user_id == actor.id

    assert f"Fine ID: {fine.id}" in (
        audit.description
    )

    assert f"Loan ID: {loan.id}" in (
        audit.description
    )

    assert "Amount: 6.00 PLN" in (
        audit.description
    )


# ==========================================
# REPEATED RETURN PROTECTION
# ==========================================

def test_return_fine_duplicate_return_protection(
    service,
    loan_service,
    data,
    unpaid_fine
):

    from app.exceptions import (
        LoanAlreadyReturnedError
    )

    actor_id = data["librarian"].id

    original_amount = unpaid_fine.amount

    original_audit_count = AuditLog.query.count()

    with pytest.raises(
        LoanAlreadyReturnedError
    ):

        loan_service.return_book(
            actor_id,
            unpaid_fine.loan_id
        )

    assert Fine.query.count() == 1

    assert Payment.query.count() == 0

    assert unpaid_fine.amount == original_amount

    assert unpaid_fine.status == "UNPAID"

    assert get_audit_count(
        "FINE_CREATED"
    ) == 1

    assert AuditLog.query.count() == (
        original_audit_count
    )


# ==========================================
# EXISTING FINE PROTECTION
# ==========================================

def test_return_fine_existing_record_protection(
    loan_service,
    data,
    overdue_loan
):

    # Intentionally create inconsistent test data:
    # an active loan already associated with a fine.

    fine = Fine(
        loan_id=overdue_loan.id,
        amount=Decimal("5.00"),
        paid_amount=Decimal("0.00"),
        status="UNPAID"
    )

    db.session.add(fine)

    db.session.commit()

    original_audit_count = AuditLog.query.count()

    with pytest.raises(
        BusinessRuleError,
        match="Active loan already has a fine"
    ):

        loan_service.return_book(
            data["librarian"].id,
            overdue_loan.id
        )

    assert overdue_loan.status == "ACTIVE"

    assert overdue_loan.returned_at is None

    assert overdue_loan.copy.status == "LOANED"

    assert Fine.query.count() == 1

    assert fine.amount == Decimal("5.00")

    assert Payment.query.count() == 0

    assert AuditLog.query.count() == (
        original_audit_count
    )


# ==========================================
# RETURN WITH EXCESSIVE FINE
# ==========================================

def test_return_fine_overflow_rollback(
    loan_service,
    setting_service,
    data,
    overdue_loan
):

    setting_service.update(
        "FINE_PER_DAY",
        Decimal("99999999.99")
    )

    actor_id = data["librarian"].id

    original_audit_count = AuditLog.query.count()

    with pytest.raises(
        BusinessRuleError,
        match="Calculated fine exceeds database limit"
    ):

        loan_service.return_book(
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

    # Correct the rate and retry the return.

    setting_service.update(
        "FINE_PER_DAY",
        Decimal("1.00")
    )

    loan = loan_service.return_book(
        actor_id,
        overdue_loan.id
    )

    assert loan.status == "RETURNED"

    assert loan.copy.status == "AVAILABLE"

    assert Fine.query.count() == 1

    assert loan.fine.amount == Decimal("6.00")

    assert get_audit_count(
        "FINE_CREATED"
    ) == 1


# ==========================================
# UNSAVED LOAN PROTECTION
# ==========================================

def test_create_return_fine_unsaved_loan(
    service,
    data
):

    loan = Loan(
        status="ACTIVE"
    )

    assert loan.id is None

    with pytest.raises(
        BusinessRuleError,
        match="Cannot create a fine for an unsaved loan"
    ):

        service._create_return_fine(
            data["admin"].id,
            loan,
            5
        )

    assert Fine.query.count() == 0

    assert Loan.query.count() == 0

    assert get_audit_count(
        "FINE_CREATED"
    ) == 0


# ==========================================
# NON-ACTIVE LOAN PROTECTION
# ==========================================

@pytest.mark.parametrize(
    "status",
    ["RETURNED", "CANCELLED"]
)
def test_create_return_fine_non_active_loan(
    service,
    loan_service,
    data,
    active_loan,
    status
):

    actor_id = data["admin"].id

    if status == "RETURNED":

        loan = loan_service.return_book(
            actor_id,
            active_loan.id
        )

    else:

        loan = loan_service.cancel_loan(
            actor_id,
            active_loan.id,
            "Test cancellation"
        )

    assert loan.status == status

    original_audit_count = AuditLog.query.count()

    with pytest.raises(
        BusinessRuleError,
        match="Fine creation requires an active loan"
    ):

        service._create_return_fine(
            actor_id,
            loan,
            5
        )

    assert loan.status == status

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0

    assert AuditLog.query.count() == (
        original_audit_count
    )


# ==========================================
# UNAUTHORIZED FINE CREATION
# ==========================================

@pytest.mark.parametrize(
    "actor_key, expected_error",
    [
        ("user", AuthorizationError),
        (None, AuthenticationError)
    ]
)
def test_create_return_fine_unauthorized(
    service,
    data,
    overdue_loan,
    actor_key,
    expected_error
):

    actor_id = (
        data[actor_key].id
        if actor_key is not None
        else None
    )

    original_audit_count = AuditLog.query.count()

    with pytest.raises(expected_error):

        service._create_return_fine(
            actor_id,
            overdue_loan,
            6
        )

    assert overdue_loan.status == "ACTIVE"

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0

    assert AuditLog.query.count() == (
        original_audit_count
    )


# ==========================================
# INVALID OVERDUE DAYS DURING CREATION
# ==========================================

def test_create_return_fine_invalid_days(
    service,
    data,
    overdue_loan
):

    original_audit_count = AuditLog.query.count()

    with pytest.raises(ValidationError):

        service._create_return_fine(
            data["librarian"].id,
            overdue_loan,
            -1
        )

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0

    assert overdue_loan.status == "ACTIVE"

    assert AuditLog.query.count() == (
        original_audit_count
    )


# ==========================================
# SHARED TRANSACTION PROTECTION
# ==========================================

def test_create_return_fine_does_not_commit(
    service,
    data,
    overdue_loan
):

    actor_id = data["librarian"].id

    original_audit_count = AuditLog.query.count()

    fine = service._create_return_fine(
        actor_id,
        overdue_loan,
        6
    )

    assert fine.id is not None

    assert fine.amount == Decimal("6.00")

    assert fine.status == "UNPAID"

    assert Fine.query.count() == 1

    assert get_audit_count(
        "FINE_CREATED"
    ) == 1

    # The caller must control the transaction.

    db.session.rollback()

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0

    assert get_audit_count(
        "FINE_CREATED"
    ) == 0

    assert AuditLog.query.count() == (
        original_audit_count
    )

    assert overdue_loan.status == "ACTIVE"

    assert overdue_loan.returned_at is None

    assert overdue_loan.copy.status == "LOANED"

# ==========================================
# MULTIPLE FINES FIXTURE
# ==========================================

@pytest.fixture
def multiple_fines(
    service,
    loan_service,
    copy_service,
    setting_service,
    data
):

    setting_service.update(
        "FINE_PER_DAY",
        Decimal("1.00")
    )

    actor_id = data["librarian"].id

    specifications = [
        (0, 10, "0.00", "UNPAID"),
        (0, 20, "5.00", "PARTIALLY_PAID"),
        (0, 30, "30.00", "PAID"),
        (1, 15, "0.00", "UNPAID"),
        (1, 25, "10.00", "PARTIALLY_PAID")
    ]

    fines = []

    for number, specification in enumerate(
        specifications,
        start=1
    ):

        reader_index, days, paid, status = specification

        reader = data["readers"][reader_index]

        book = data["books"][
            (number - 1) % len(data["books"])
        ]

        copy = copy_service.create_copy(
            actor_id,
            book.id,
            f"MULTI-FINE-{number:03d}"
        )

        loan = loan_service.borrow_book(
            actor_id,
            reader.id,
            copy.id
        )

        now = loan_service.now()

        loan.due_date = (
            now - timedelta(
                days=days - 1,
                hours=12
            )
        )

        loan.borrowed_at = (
            loan.due_date - timedelta(days=30)
        )

        db.session.commit()

        loan_service.return_book(
            actor_id,
            loan.id
        )

        fine = service.get_by_loan(
            actor_id,
            loan.id
        )

        assert fine is not None

        assert fine.amount == Decimal(days).quantize(
            Decimal("0.01")
        )

        paid_amount = Decimal(paid)

        if paid_amount > Decimal("0.00"):

            payment = Payment(
                fine_id=fine.id,
                amount=paid_amount,
                method="CASH"
            )

            db.session.add(payment)

        fine.paid_amount = paid_amount

        fine.status = status

        db.session.commit()

        fines.append(fine)

    assert Fine.query.count() == 5

    assert Payment.query.count() == 3

    return {
        "fines": fines,
        "unpaid": [fines[0], fines[3]],
        "partially_paid": [fines[1], fines[4]],
        "paid": [fines[2]],
        "reader_one": fines[:3],
        "reader_two": fines[3:],
        "reader_three": []
    }


# ==========================================
# HELPER FUNCTION
# ==========================================

def fine_ids(fines):

    return {
        fine.id
        for fine in fines
    }


# ==========================================
# INTERNAL RECORD ACCESS
# ==========================================

def test_fine_internal_record_access(
    service,
    unpaid_fine
):

    fine = service._get_fine(
        unpaid_fine.id
    )

    loan = service._get_loan(
        unpaid_fine.loan_id
    )

    assert fine.id == unpaid_fine.id

    assert loan.id == unpaid_fine.loan_id

    assert loan.status == "RETURNED"

    assert fine.loan.id == loan.id


@pytest.mark.parametrize(
    "method_name",
    ["_get_fine", "_get_loan"]
)
def test_fine_internal_record_not_found(
    service,
    method_name
):

    method = getattr(
        service,
        method_name
    )

    with pytest.raises(NotFoundError):

        method(999999)


@pytest.mark.parametrize(
    "method_name",
    ["_get_fine", "_get_loan"]
)
def test_fine_internal_invalid_identifier(
    service,
    method_name
):

    method = getattr(
        service,
        method_name
    )

    with pytest.raises(ValidationError):

        method(0)


# ==========================================
# GET FINE BY ID
# ==========================================

def test_fine_get_by_id_multiple_records(
    service,
    data,
    multiple_fines
):

    actor_id = data["admin"].id

    for expected in multiple_fines["fines"]:

        result = service.get_by_id(
            actor_id,
            expected.id
        )

        assert result.id == expected.id

        assert result.loan_id == expected.loan_id

        assert result.amount == expected.amount

        assert result.paid_amount == (
            expected.paid_amount
        )

        assert result.status == expected.status


# ==========================================
# GET FINE BY LOAN
# ==========================================

def test_fine_get_by_loan_multiple_records(
    service,
    data,
    multiple_fines
):

    actor_id = data["librarian"].id

    for expected in multiple_fines["fines"]:

        result = service.get_by_loan(
            actor_id,
            expected.loan_id
        )

        assert result is not None

        assert result.id == expected.id

        assert result.loan_id == expected.loan_id


# ==========================================
# GET ALL FINES
# ==========================================

def test_fine_get_all_multiple_records(
    service,
    data,
    multiple_fines
):

    result = service.get_all(
        data["admin"].id
    )

    assert len(result) == 5

    assert fine_ids(result) == fine_ids(
        multiple_fines["fines"]
    )

    assert all(
        fine.loan.status == "RETURNED"
        for fine in result
    )


# ==========================================
# READER FINE HISTORY
# ==========================================

@pytest.mark.parametrize(
    "reader_index, expected_key",
    [
        (0, "reader_one"),
        (1, "reader_two"),
        (2, "reader_three")
    ]
)
def test_fine_get_by_reader_history(
    service,
    data,
    multiple_fines,
    reader_index,
    expected_key
):

    reader = data["readers"][reader_index]

    result = service.get_by_reader(
        data["librarian"].id,
        reader.id
    )

    expected = multiple_fines[
        expected_key
    ]

    assert len(result) == len(expected)

    assert fine_ids(result) == fine_ids(
        expected
    )

    assert all(
        fine.loan.reader_id == reader.id
        for fine in result
    )


# ==========================================
# STATUS FILTERING
# ==========================================

@pytest.mark.parametrize(
    "status, expected_key",
    [
        ("UNPAID", "unpaid"),
        ("PARTIALLY_PAID", "partially_paid"),
        ("PAID", "paid")
    ]
)
def test_fine_filter_by_status(
    service,
    data,
    multiple_fines,
    status,
    expected_key
):

    result = service.get_by_status(
        data["librarian"].id,
        status
    )

    expected = multiple_fines[
        expected_key
    ]

    assert len(result) == len(expected)

    assert fine_ids(result) == fine_ids(
        expected
    )

    assert all(
        fine.status == status
        for fine in result
    )


def test_fine_filter_status_normalization(
    service,
    data,
    multiple_fines
):

    result = service.get_by_status(
        data["admin"].id,
        "  partially_paid  "
    )

    assert len(result) == 2

    assert fine_ids(result) == fine_ids(
        multiple_fines["partially_paid"]
    )


def test_fine_filter_invalid_status(
    service,
    data,
    multiple_fines
):

    original_count = Fine.query.count()

    with pytest.raises(ValidationError):

        service.get_by_status(
            data["admin"].id,
            "UNKNOWN"
        )

    assert Fine.query.count() == original_count


# ==========================================
# GLOBAL UNPAID FINES
# ==========================================

def test_fine_get_unpaid_multiple_records(
    service,
    data,
    multiple_fines
):

    result = service.get_unpaid_fines(
        data["librarian"].id
    )

    expected = (
        multiple_fines["unpaid"]
        + multiple_fines["partially_paid"]
    )

    assert len(result) == 4

    assert fine_ids(result) == fine_ids(
        expected
    )

    assert all(
        fine.status != "PAID"
        for fine in result
    )


# ==========================================
# OWN FINE HISTORY
# ==========================================

@pytest.mark.parametrize(
    "reader_index, expected_key",
    [
        (0, "reader_one"),
        (1, "reader_two"),
        (2, "reader_three")
    ]
)
def test_fine_get_own_history(
    service,
    data,
    multiple_fines,
    reader_index,
    expected_key
):

    reader = data["readers"][reader_index]

    result = service.get_own_fines(
        reader.user_id
    )

    expected = multiple_fines[
        expected_key
    ]

    assert len(result) == len(expected)

    assert fine_ids(result) == fine_ids(
        expected
    )

    assert all(
        fine.loan.reader_id == reader.id
        for fine in result
    )


# ==========================================
# OWN UNPAID FINES
# ==========================================

@pytest.mark.parametrize(
    "reader_index, expected_count",
    [
        (0, 2),
        (1, 2),
        (2, 0)
    ]
)
def test_fine_get_own_unpaid_history(
    service,
    data,
    multiple_fines,
    reader_index,
    expected_count
):

    reader = data["readers"][reader_index]

    result = service.get_own_unpaid_fines(
        reader.user_id
    )

    expected = [
        fine
        for fine in multiple_fines["fines"]
        if fine.loan.reader_id == reader.id
        and fine.status != "PAID"
    ]

    assert len(result) == expected_count

    assert fine_ids(result) == fine_ids(
        expected
    )

    assert all(
        fine.loan.reader_id == reader.id
        for fine in result
    )

    assert all(
        fine.status in (
            "UNPAID",
            "PARTIALLY_PAID"
        )
        for fine in result
    )


# ==========================================
# FINE COUNT
# ==========================================

def test_fine_count_multiple_records(
    service,
    data,
    multiple_fines
):

    assert service.count(
        data["admin"].id
    ) == 5

    assert service.count(
        data["librarian"].id
    ) == 5

    assert Fine.query.count() == 5


# ==========================================
# EMPTY DATABASE RESULTS
# ==========================================

def test_fine_empty_results(
    service,
    data
):

    actor_id = data["admin"].id

    reader = data["reader"]

    assert service.get_all(
        actor_id
    ) == []

    assert service.get_by_reader(
        actor_id,
        reader.id
    ) == []

    assert service.get_unpaid_fines(
        actor_id
    ) == []

    for status in service.VALID_STATUSES:

        assert service.get_by_status(
            actor_id,
            status
        ) == []

    assert service.get_own_fines(
        reader.user_id
    ) == []

    assert service.get_own_unpaid_fines(
        reader.user_id
    ) == []

    assert service.count(
        actor_id
    ) == 0


# ==========================================
# LOAN WITHOUT RECORDED FINE
# ==========================================

def test_fine_get_active_loan_without_record(
    service,
    data,
    overdue_loan
):

    actor_id = data["librarian"].id

    assert overdue_loan.status == "ACTIVE"

    assert service.get_by_loan(
        actor_id,
        overdue_loan.id
    ) is None

    assert service.get_by_loan(
        data["reader"].user_id,
        overdue_loan.id
    ) is None

    assert Fine.query.count() == 0

    assert Payment.query.count() == 0


# ==========================================
# DATABASE RECORD RELOADING
# ==========================================

def test_fine_record_reloading(
    service,
    data,
    multiple_fines
):

    actor_id = data["admin"].id

    expected = {
        fine.id: (
            fine.loan_id,
            fine.amount,
            fine.paid_amount,
            fine.status
        )
        for fine in multiple_fines["fines"]
    }

    original_audit_count = AuditLog.query.count()

    db.session.remove()

    fresh_service = FineService()

    records = fresh_service.get_all(
        actor_id
    )

    actual = {
        fine.id: (
            fine.loan_id,
            fine.amount,
            fine.paid_amount,
            fine.status
        )
        for fine in records
    }

    assert actual == expected

    assert len(records) == 5

    assert Fine.query.count() == 5

    assert Payment.query.count() == 3

    assert AuditLog.query.count() == (
        original_audit_count
    )

    for fine in records:

        assert fine.loan.status == "RETURNED"

        assert get_payment_total(
            fine.id
        ) == fine.paid_amount



# ==========================================
# FINANCIAL SUMMARY ASSERTION HELPER
# ==========================================

def assert_financial_summary(
    summary,
    total_fines,
    unpaid_fines,
    partially_paid_fines,
    paid_fines,
    total_amount,
    total_paid,
    total_unpaid
):

    assert summary["total_fines"] == total_fines

    assert summary["unpaid_fines"] == unpaid_fines

    assert summary["partially_paid_fines"] == (
        partially_paid_fines
    )

    assert summary["paid_fines"] == paid_fines

    assert summary["total_amount"] == (
        Decimal(total_amount)
    )

    assert summary["total_paid"] == (
        Decimal(total_paid)
    )

    assert summary["total_unpaid"] == (
        Decimal(total_unpaid)
    )

    # Verify financial precision.

    for key in (
        "total_amount",
        "total_paid",
        "total_unpaid"
    ):

        assert isinstance(
            summary[key],
            Decimal
        )

        assert summary[key].as_tuple().exponent == -2

    # Verify mathematical consistency.

    assert summary["total_amount"] == (
        summary["total_paid"]
        + summary["total_unpaid"]
    )

    assert summary["total_fines"] == (
        summary["unpaid_fines"]
        + summary["partially_paid_fines"]
        + summary["paid_fines"]
    )


# ==========================================
# INDIVIDUAL FINE BALANCE
# ==========================================

@pytest.mark.parametrize(
    "fine_index, expected",
    [
        (0, "10.00"),
        (1, "15.00"),
        (2, "0.00"),
        (3, "15.00"),
        (4, "15.00")
    ]
)
def test_fine_remaining_amount_multiple_records(
    service,
    data,
    multiple_fines,
    fine_index,
    expected
):

    fine = multiple_fines["fines"][fine_index]

    result = service.get_remaining_amount(
        data["librarian"].id,
        fine.id
    )

    assert result == Decimal(expected)

    assert isinstance(result, Decimal)

    assert result.as_tuple().exponent == -2

    assert result >= Decimal("0.00")

    assert result <= fine.amount


# ==========================================
# READER TOTAL UNPAID AMOUNT
# ==========================================

@pytest.mark.parametrize(
    "actor_key",
    ["admin", "librarian"]
)
@pytest.mark.parametrize(
    "reader_index, expected",
    [
        (0, "25.00"),
        (1, "30.00"),
        (2, "0.00")
    ]
)
def test_fine_total_unpaid_by_reader_multiple(
    service,
    data,
    multiple_fines,
    actor_key,
    reader_index,
    expected
):

    actor = data[actor_key]

    reader = data["readers"][reader_index]

    result = service.get_total_unpaid_by_reader(
        actor.id,
        reader.id
    )

    assert result == Decimal(expected)

    assert isinstance(result, Decimal)

    assert result.as_tuple().exponent == -2


# ==========================================
# OWN READER BALANCE
# ==========================================

@pytest.mark.parametrize(
    "reader_index, expected",
    [
        (0, "25.00"),
        (1, "30.00"),
        (2, "0.00")
    ]
)
def test_fine_own_total_unpaid_multiple(
    service,
    data,
    multiple_fines,
    reader_index,
    expected
):

    reader = data["readers"][reader_index]

    result = service.get_own_total_unpaid(
        reader.user_id
    )

    assert result == Decimal(expected)

    assert isinstance(result, Decimal)

    assert result.as_tuple().exponent == -2


# ==========================================
# READER SUMMARY TEST DATA
# ==========================================

READER_SUMMARY_CASES = [
    (
        0,
        3, 1, 1, 1,
        "60.00", "35.00", "25.00"
    ),
    (
        1,
        2, 1, 1, 0,
        "40.00", "10.00", "30.00"
    ),
    (
        2,
        0, 0, 0, 0,
        "0.00", "0.00", "0.00"
    )
]


# ==========================================
# READER FINANCIAL SUMMARY
# ==========================================

@pytest.mark.parametrize(
    "actor_key",
    ["admin", "librarian"]
)
@pytest.mark.parametrize(
    "reader_index, total, unpaid, partial, paid, " 
    "amount, paid_amount, remaining",
    READER_SUMMARY_CASES
)
def test_fine_reader_summary_multiple(
    service,
    data,
    multiple_fines,
    actor_key,
    reader_index,
    total,
    unpaid,
    partial,
    paid,
    amount,
    paid_amount,
    remaining
):

    reader = data["readers"][reader_index]

    summary = service.get_reader_summary(
        data[actor_key].id,
        reader.id
    )

    assert summary["reader_id"] == reader.id

    assert_financial_summary(
        summary,
        total,
        unpaid,
        partial,
        paid,
        amount,
        paid_amount,
        remaining
    )


# ==========================================
# OWN FINANCIAL SUMMARY
# ==========================================

@pytest.mark.parametrize(
    "reader_index, total, unpaid, partial, paid, "
    "amount, paid_amount, remaining",
    READER_SUMMARY_CASES
)
def test_fine_own_summary_multiple(
    service,
    data,
    multiple_fines,
    reader_index,
    total,
    unpaid,
    partial,
    paid,
    amount,
    paid_amount,
    remaining
):

    reader = data["readers"][reader_index]

    summary = service.get_own_summary(
        reader.user_id
    )

    assert summary["reader_id"] == reader.id

    assert_financial_summary(
        summary,
        total,
        unpaid,
        partial,
        paid,
        amount,
        paid_amount,
        remaining
    )


# ==========================================
# GLOBAL FINANCIAL SUMMARY
# ==========================================

@pytest.mark.parametrize(
    "actor_key",
    ["admin", "librarian"]
)
def test_fine_global_summary_multiple(
    service,
    data,
    multiple_fines,
    actor_key
):

    summary = service.get_summary(
        data[actor_key].id
    )

    assert_financial_summary(
        summary,
        5,
        2,
        2,
        1,
        "100.00",
        "45.00",
        "55.00"
    )

    assert "reader_id" not in summary


# ==========================================
# EMPTY FINANCIAL SUMMARY
# ==========================================

def test_fine_empty_financial_summary(
    service,
    data
):

    actor_id = data["admin"].id

    reader = data["reader"]

    summaries = [
        service.get_summary(actor_id),
        service.get_reader_summary(
            actor_id,
            reader.id
        ),
        service.get_own_summary(
            reader.user_id
        )
    ]

    for summary in summaries:

        assert_financial_summary(
            summary,
            0,
            0,
            0,
            0,
            "0.00",
            "0.00",
            "0.00"
        )

    assert service.get_total_unpaid_by_reader(
        actor_id,
        reader.id
    ) == Decimal("0.00")

    assert service.get_own_total_unpaid(
        reader.user_id
    ) == Decimal("0.00")


# ==========================================
# GLOBAL AND READER SUMMARY CONSISTENCY
# ==========================================

def test_fine_summary_aggregation_consistency(
    service,
    data,
    multiple_fines
):

    actor_id = data["admin"].id

    global_summary = service.get_summary(
        actor_id
    )

    reader_summaries = [
        service.get_reader_summary(
            actor_id,
            reader.id
        )
        for reader in data["readers"]
    ]

    for key in (
        "total_fines",
        "unpaid_fines",
        "partially_paid_fines",
        "paid_fines"
    ):

        expected = sum(
            summary[key]
            for summary in reader_summaries
        )

        assert global_summary[key] == expected

    for key in (
        "total_amount",
        "total_paid",
        "total_unpaid"
    ):

        expected = sum(
            (
                summary[key]
                for summary in reader_summaries
            ),
            Decimal("0.00")
        )

        assert global_summary[key] == expected

    individual_balances = sum(
        (
            service.get_remaining_amount(
                actor_id,
                fine.id
            )
            for fine in multiple_fines["fines"]
        ),
        Decimal("0.00")
    )

    assert individual_balances == (
        global_summary["total_unpaid"]
    )

    assert individual_balances == Decimal("55.00")


# ==========================================
# FRACTIONAL MONETARY PRECISION
# ==========================================

def test_fine_summary_fractional_amounts(
    service,
    loan_service,
    copy_service,
    setting_service,
    data
):

    actor_id = data["librarian"].id

    reader = data["reader"]

    setting_service.update(
        "FINE_PER_DAY",
        Decimal("0.01")
    )

    specifications = [
        (10, "0.03"),
        (20, "0.07"),
        (33, "0.11")
    ]

    for index, (days, paid) in enumerate(
        specifications,
        start=1
    ):

        copy = copy_service.create_copy(
            actor_id,
            data["book"].id,
            f"DECIMAL-FINE-{index:03d}"
        )

        loan = loan_service.borrow_book(
            actor_id,
            reader.id,
            copy.id
        )

        now = loan_service.now()

        loan.due_date = (
            now - timedelta(
                days=days - 1,
                hours=12
            )
        )

        loan.borrowed_at = (
            loan.due_date - timedelta(days=30)
        )

        db.session.commit()

        loan_service.return_book(
            actor_id,
            loan.id
        )

        fine = service.get_by_loan(
            actor_id,
            loan.id
        )

        expected_amount = (
            Decimal(days) * Decimal("0.01")
        )

        assert fine.amount == expected_amount

        payment = Payment(
            fine_id=fine.id,
            amount=Decimal(paid),
            method="CASH"
        )

        db.session.add(payment)

        fine.paid_amount = Decimal(paid)

        fine.status = "PARTIALLY_PAID"

        db.session.commit()

    summary = service.get_summary(actor_id)

    assert_financial_summary(
        summary,
        3,
        0,
        3,
        0,
        "0.63",
        "0.21",
        "0.42"
    )

    assert service.get_own_total_unpaid(
        reader.user_id
    ) == Decimal("0.42")


# ==========================================
# SUMMARY UPDATE AFTER FULL PAYMENT
# ==========================================

def test_fine_summary_after_full_payment(
    service,
    data,
    multiple_fines
):

    actor_id = data["admin"].id

    fine = multiple_fines["fines"][1]

    before = service.get_summary(actor_id)

    assert before["total_unpaid"] == (
        Decimal("55.00")
    )

    remaining = service.get_remaining_amount(
        actor_id,
        fine.id
    )

    assert remaining == Decimal("15.00")

    payment = Payment(
        fine_id=fine.id,
        amount=remaining,
        method="CARD"
    )

    db.session.add(payment)

    fine.paid_amount = fine.amount

    fine.status = "PAID"

    db.session.commit()

    after = service.get_summary(actor_id)

    assert_financial_summary(
        after,
        5,
        2,
        1,
        2,
        "100.00",
        "60.00",
        "40.00"
    )

    assert service.get_remaining_amount(
        actor_id,
        fine.id
    ) == Decimal("0.00")

    assert service.get_own_total_unpaid(
        data["reader"].user_id
    ) == Decimal("10.00")

    assert Payment.query.count() == 4


# ==========================================
# FINANCIAL CONSISTENCY TEST UTILITIES
# ==========================================

from types import SimpleNamespace


def make_consistency_fine(
    amount=Decimal("10.00"),
    paid_amount=Decimal("0.00"),
    status="UNPAID"
):

    from datetime import datetime

    due_date = datetime(2026, 1, 1, 12, 0, 0)

    loan = SimpleNamespace(
        id=1,
        reader_id=1,
        status="RETURNED",
        due_date=due_date,
        returned_at=due_date + timedelta(days=10)
    )

    return SimpleNamespace(
        id=1,
        loan_id=1,
        loan=loan,
        amount=amount,
        paid_amount=paid_amount,
        status=status
    )


# ==========================================
# VALID FINANCIAL CONSISTENCY
# ==========================================

@pytest.mark.parametrize(
    "fixture_name",
    [
        "unpaid_fine",
        "partially_paid_fine",
        "paid_fine"
    ]
)
def test_fine_consistency_valid_records(
    service,
    request,
    fixture_name
):

    fine = request.getfixturevalue(
        fixture_name
    )

    result = service._ensure_consistency(
        fine
    )

    assert result is fine

    assert get_payment_total(
        fine.id
    ) == fine.paid_amount

    assert fine.loan.status == "RETURNED"


# ==========================================
# INVALID FINE AMOUNTS
# ==========================================

@pytest.mark.parametrize(
    "amount",
    [
        Decimal("0.00"),
        Decimal("-1.00"),
        Decimal("0.001"),
        Decimal("100000000.00"),
        Decimal("NaN"),
        Decimal("Infinity"),
        None,
        True,
        10.50,
        "invalid"
    ]
)
def test_fine_consistency_invalid_amount(
    service,
    amount
):

    fine = make_consistency_fine(
        amount=amount
    )

    with pytest.raises(
        BusinessRuleError,
        match="Fine contains invalid monetary values"
    ):

        service._ensure_consistency(fine)


# ==========================================
# INVALID PAID AMOUNTS
# ==========================================

@pytest.mark.parametrize(
    "paid_amount",
    [
        Decimal("-0.01"),
        Decimal("1.001"),
        Decimal("100000000.00"),
        Decimal("NaN"),
        Decimal("Infinity"),
        None,
        True,
        1.50
    ]
)
def test_fine_consistency_invalid_paid_amount(
    service,
    paid_amount
):

    fine = make_consistency_fine(
        paid_amount=paid_amount
    )

    with pytest.raises(
        BusinessRuleError,
        match="Fine contains invalid monetary values"
    ):

        service._ensure_consistency(fine)


# ==========================================
# OVERPAYMENT CONSISTENCY
# ==========================================

@pytest.mark.parametrize(
    "paid_amount",
    [
        Decimal("10.01"),
        Decimal("20.00"),
        Decimal("99999999.99")
    ]
)
def test_fine_consistency_overpayment(
    service,
    paid_amount
):

    fine = make_consistency_fine(
        amount=Decimal("10.00"),
        paid_amount=paid_amount
    )

    with pytest.raises(
        BusinessRuleError,
        match="Paid amount exceeds fine amount"
    ):

        service._ensure_consistency(fine)


# ==========================================
# MISSING LOAN
# ==========================================

def test_fine_consistency_missing_loan(
    service
):

    fine = make_consistency_fine()

    fine.loan = None

    with pytest.raises(
        BusinessRuleError,
        match="Fine has no associated loan"
    ):

        service._ensure_consistency(fine)


# ==========================================
# NON-RETURNED LOAN
# ==========================================

@pytest.mark.parametrize(
    "status",
    [
        "ACTIVE",
        "CANCELLED",
        "UNKNOWN"
    ]
)
def test_fine_consistency_non_returned_loan(
    service,
    status
):

    fine = make_consistency_fine()

    fine.loan.status = status

    with pytest.raises(
        BusinessRuleError,
        match="Fine belongs to a non-returned loan"
    ):

        service._ensure_consistency(fine)


# ==========================================
# MISSING RETURN DATE
# ==========================================

def test_fine_consistency_missing_return_date(
    service
):

    fine = make_consistency_fine()

    fine.loan.returned_at = None

    with pytest.raises(
        BusinessRuleError,
        match="Returned loan has no return date"
    ):

        service._ensure_consistency(fine)


# ==========================================
# ON-TIME RETURN CONSISTENCY
# ==========================================

@pytest.mark.parametrize(
    "seconds",
    [-86400, -1, 0]
)
def test_fine_consistency_on_time_return(
    service,
    seconds
):

    fine = make_consistency_fine()

    fine.loan.returned_at = (
        fine.loan.due_date
        + timedelta(seconds=seconds)
    )

    with pytest.raises(
        BusinessRuleError,
        match="Fine belongs to a loan returned on time"
    ):

        service._ensure_consistency(fine)


# ==========================================
# INVALID FINANCIAL STATUS
# ==========================================

@pytest.mark.parametrize(
    "paid_amount, status",
    [
        ("0.00", "PAID"),
        ("0.00", "PARTIALLY_PAID"),
        ("5.00", "UNPAID"),
        ("5.00", "PAID"),
        ("10.00", "UNPAID"),
        ("10.00", "PARTIALLY_PAID"),
        ("0.00", "UNKNOWN"),
        ("0.00", None)
    ]
)
def test_fine_consistency_invalid_status(
    service,
    paid_amount,
    status
):

    fine = make_consistency_fine(
        paid_amount=Decimal(paid_amount),
        status=status
    )

    with pytest.raises(
        BusinessRuleError,
        match="Fine status is inconsistent"
    ):

        service._ensure_consistency(fine)


# ==========================================
# INVALID PAYMENT RECORDS
# ==========================================

@pytest.mark.parametrize(
    "payment_amount",
    [
        Decimal("0.00"),
        Decimal("-1.00"),
        Decimal("0.001"),
        Decimal("100000000.00"),
        Decimal("NaN"),
        Decimal("Infinity"),
        None,
        True,
        1.25
    ]
)
def test_fine_consistency_invalid_payment(
    service,
    monkeypatch,
    payment_amount
):

    fine = make_consistency_fine(
        paid_amount=Decimal("5.00"),
        status="PARTIALLY_PAID"
    )

    payment = SimpleNamespace(
        amount=payment_amount
    )

    monkeypatch.setattr(
        service.payment_repository,
        "get_by_fine",
        lambda fine_id: [payment]
    )

    with pytest.raises(
        BusinessRuleError,
        match="Fine contains an invalid payment"
    ):

        service._ensure_consistency(fine)


# ==========================================
# PAYMENT SUM INCONSISTENCY
# ==========================================

@pytest.mark.parametrize(
    "paid_amount, status, payment_amounts",
    [
        ("5.00", "PARTIALLY_PAID", []),

        (
            "5.00",
            "PARTIALLY_PAID",
            ["3.00"]
        ),

        (
            "5.00",
            "PARTIALLY_PAID",
            ["6.00"]
        ),

        (
            "0.00",
            "UNPAID",
            ["1.00"]
        ),

        (
            "10.00",
            "PAID",
            ["9.99"]
        ),

        (
            "5.00",
            "PARTIALLY_PAID",
            ["2.00", "2.00"]
        )
    ]
)
def test_fine_consistency_payment_sum_mismatch(
    service,
    monkeypatch,
    paid_amount,
    status,
    payment_amounts
):

    fine = make_consistency_fine(
        paid_amount=Decimal(paid_amount),
        status=status
    )

    payments = [
        SimpleNamespace(
            amount=Decimal(amount)
        )
        for amount in payment_amounts
    ]

    monkeypatch.setattr(
        service.payment_repository,
        "get_by_fine",
        lambda fine_id: payments
    )

    with pytest.raises(
        BusinessRuleError,
        match="Payment records are inconsistent"
    ):

        service._ensure_consistency(fine)


# ==========================================
# MULTIPLE VALID PAYMENT RECORDS
# ==========================================

@pytest.mark.parametrize(
    "paid_amount, status, payment_amounts",
    [
        (
            "5.00",
            "PARTIALLY_PAID",
            ["2.00", "3.00"]
        ),

        (
            "10.00",
            "PAID",
            ["2.00", "3.00", "5.00"]
        ),

        (
            "0.30",
            "PARTIALLY_PAID",
            ["0.10", "0.20"]
        ),

        (
            "0.00",
            "UNPAID",
            []
        )
    ]
)
def test_fine_consistency_multiple_payments(
    service,
    monkeypatch,
    paid_amount,
    status,
    payment_amounts
):

    fine = make_consistency_fine(
        paid_amount=Decimal(paid_amount),
        status=status
    )

    payments = [
        SimpleNamespace(
            amount=Decimal(amount)
        )
        for amount in payment_amounts
    ]

    monkeypatch.setattr(
        service.payment_repository,
        "get_by_fine",
        lambda fine_id: payments
    )

    result = service._ensure_consistency(
        fine
    )

    assert result is fine


# ==========================================
# PUBLIC OPERATIONS CONSISTENCY PROTECTION
# ==========================================

FINE_CONSISTENCY_METHODS = [
    "get_remaining_amount",
    "get_total_unpaid_by_reader",
    "get_own_total_unpaid",
    "get_reader_summary",
    "get_own_summary",
    "get_summary"
]


@pytest.mark.parametrize(
    "method_name",
    FINE_CONSISTENCY_METHODS
)
def test_fine_public_operations_reject_inconsistency(
    service,
    data,
    unpaid_fine,
    method_name
):

    # Intentionally create a mismatch between
    # paid_amount and payment records.

    unpaid_fine.paid_amount = Decimal("2.00")

    unpaid_fine.status = "PARTIALLY_PAID"

    db.session.commit()

    actor_id = (
        data["user"].id
        if method_name.startswith("get_own_")
        else data["admin"].id
    )

    original_audit_count = AuditLog.query.count()

    with pytest.raises(
        BusinessRuleError,
        match="Payment records are inconsistent"
    ):

        call_fine_method(
            service,
            method_name,
            actor_id,
            unpaid_fine
        )

    assert Fine.query.count() == 1

    assert Payment.query.count() == 0

    assert unpaid_fine.paid_amount == (
        Decimal("2.00")
    )

    assert unpaid_fine.status == "PARTIALLY_PAID"

    assert AuditLog.query.count() == (
        original_audit_count
    )


# ==========================================
# INCONSISTENT RECORD IN GLOBAL SUMMARY
# ==========================================

def test_fine_summary_rejects_single_invalid_record(
    service,
    data,
    multiple_fines
):

    actor_id = data["admin"].id

    fine = multiple_fines["fines"][4]

    # Original payment total is 10.00.
    # Intentionally change the recorded balance.

    fine.paid_amount = Decimal("11.00")

    db.session.commit()

    with pytest.raises(
        BusinessRuleError,
        match="Payment records are inconsistent"
    ):

        service.get_summary(actor_id)

    assert Fine.query.count() == 5

    assert Payment.query.count() == 3

    # The first reader still has consistent data.

    summary = service.get_reader_summary(
        actor_id,
        data["readers"][0].id
    )

    assert_financial_summary(
        summary,
        3,
        1,
        1,
        1,
        "60.00",
        "35.00",
        "25.00"
    )

    # The affected reader's summary must fail.

    with pytest.raises(BusinessRuleError):

        service.get_reader_summary(
            actor_id,
            data["readers"][1].id
        )


# ==========================================
# READ ACCESS TO INCONSISTENT RECORDS
# ==========================================

def test_fine_inconsistent_record_diagnostic_access(
    service,
    data,
    unpaid_fine
):

    actor_id = data["admin"].id

    unpaid_fine.status = "PAID"

    db.session.commit()

    # Basic record access remains possible
    # for diagnostic purposes.

    result = service.get_by_id(
        actor_id,
        unpaid_fine.id
    )

    assert result.id == unpaid_fine.id

    assert result.status == "PAID"

    assert result.paid_amount == (
        Decimal("0.00")
    )

    # Financial calculations must reject
    # the inconsistent record.

    with pytest.raises(
        BusinessRuleError,
        match="Fine status is inconsistent"
    ):

        service.get_remaining_amount(
            actor_id,
            unpaid_fine.id
        )


# ==========================================
# RECOVERY AFTER CORRECTING DATA
# ==========================================

def test_fine_consistency_after_data_correction(
    service,
    data,
    unpaid_fine
):

    actor_id = data["admin"].id

    unpaid_fine.paid_amount = Decimal("2.00")

    unpaid_fine.status = "PARTIALLY_PAID"

    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.get_remaining_amount(
            actor_id,
            unpaid_fine.id
        )

    # Correct the missing payment in the
    # isolated test database.

    payment = Payment(
        fine_id=unpaid_fine.id,
        amount=Decimal("2.00"),
        method="CASH"
    )

    db.session.add(payment)

    db.session.commit()

    assert service._ensure_consistency(
        unpaid_fine
    ) is unpaid_fine

    assert service.get_remaining_amount(
        actor_id,
        unpaid_fine.id
    ) == Decimal("4.00")

    assert service.get_own_total_unpaid(
        data["user"].id
    ) == Decimal("4.00")

    summary = service.get_summary(actor_id)

    assert_financial_summary(
        summary,
        1,
        0,
        1,
        0,
        "6.00",
        "2.00",
        "4.00"
    )


# ==========================================
# CONSISTENCY CHECK HAS NO SIDE EFFECTS
# ==========================================

def test_fine_consistency_check_has_no_side_effects(
    service,
    partially_paid_fine
):

    fine = partially_paid_fine

    original_audit_count = AuditLog.query.count()

    original_payment_count = Payment.query.count()

    original_amount = fine.amount

    original_paid_amount = fine.paid_amount

    original_status = fine.status

    for _ in range(5):

        result = service._ensure_consistency(
            fine
        )

        assert result is fine

    assert Fine.query.count() == 1

    assert Payment.query.count() == (
        original_payment_count
    )

    assert AuditLog.query.count() == (
        original_audit_count
    )

    assert fine.amount == original_amount

    assert fine.paid_amount == original_paid_amount

    assert fine.status == original_status


# ==========================================
# AUDIT AND TRANSACTION TESTS
# ==========================================

from sqlalchemy.exc import SQLAlchemyError


# ==========================================
# TRANSACTION STATE HELPER
# ==========================================

def capture_fine_transaction_state(loan):

    return {
        "loan_id": loan.id,
        "loan_status": loan.status,
        "returned_at": loan.returned_at,
        "copy_id": loan.copy_id,
        "copy_status": loan.copy.status,
        "fine_count": Fine.query.count(),
        "payment_count": Payment.query.count(),
        "audit_count": AuditLog.query.count(),
        "fine_audit_count": get_audit_count(
            "FINE_CREATED"
        ),
        "return_audit_count": get_audit_count(
            "LOAN_RETURNED"
        )
    }


def assert_fine_transaction_rolled_back(
    original
):

    # Reload the records from the database.

    db.session.remove()

    loan = db.session.get(
        Loan,
        original["loan_id"]
    )

    copy = db.session.get(
        Copy,
        original["copy_id"]
    )

    assert loan is not None

    assert copy is not None

    assert loan.status == original["loan_status"]

    assert loan.returned_at == (
        original["returned_at"]
    )

    assert copy.status == original["copy_status"]

    assert Fine.query.count() == (
        original["fine_count"]
    )

    assert Payment.query.count() == (
        original["payment_count"]
    )

    assert AuditLog.query.count() == (
        original["audit_count"]
    )

    assert get_audit_count(
        "FINE_CREATED"
    ) == original["fine_audit_count"]

    assert get_audit_count(
        "LOAN_RETURNED"
    ) == original["return_audit_count"]


# ==========================================
# TRANSACTION FAILURE INJECTION
# ==========================================

@pytest.mark.parametrize(
    "failure_stage",
    [
        "fine_repository",
        "fine_audit",
        "reservation_queue",
        "loan_audit"
    ]
)
@pytest.mark.parametrize(
    "exception_type, expected_error",
    [
        (RuntimeError, RuntimeError),
        (SQLAlchemyError, DatabaseError)
    ]
)
def test_fine_transaction_failure_rollback(
    loan_service,
    data,
    overdue_loan,
    monkeypatch,
    failure_stage,
    exception_type,
    expected_error
):

    actor_id = data["librarian"].id

    loan_id = overdue_loan.id

    original = capture_fine_transaction_state(
        overdue_loan
    )

    original_add = (
        loan_service.fine_repository.add
    )

    original_log = (
        loan_service.audit_service.log
    )

    original_process_queue = (
        loan_service.reservation_service._process_queue
    )

    failure_calls = []

    def raise_failure():

        failure_calls.append(failure_stage)

        raise exception_type(
            "Simulated transaction failure"
        )

    def failing_add(*args, **kwargs):

        result = original_add(
            *args,
            **kwargs
        )

        # Ensure that the INSERT reaches
        # the active database transaction.

        db.session.flush()

        raise_failure()

        return result

    def failing_log(action, *args, **kwargs):

        result = original_log(
            action,
            *args,
            **kwargs
        )

        should_fail = (
            failure_stage == "fine_audit"
            and action == "FINE_CREATED"
        ) or (
            failure_stage == "loan_audit"
            and action == "LOAN_RETURNED"
        )

        if should_fail:

            db.session.flush()

            raise_failure()

        return result

    def failing_process_queue(*args, **kwargs):

        result = original_process_queue(
            *args,
            **kwargs
        )

        db.session.flush()

        raise_failure()

        return result

    with monkeypatch.context() as patch:

        if failure_stage == "fine_repository":

            patch.setattr(
                loan_service.fine_repository,
                "add",
                failing_add
            )

        elif failure_stage in (
            "fine_audit",
            "loan_audit"
        ):

            patch.setattr(
                loan_service.audit_service,
                "log",
                failing_log
            )

        elif failure_stage == "reservation_queue":

            patch.setattr(
                loan_service.reservation_service,
                "_process_queue",
                failing_process_queue
            )

        with pytest.raises(expected_error):

            loan_service.return_book(
                actor_id,
                loan_id
            )

        assert failure_calls == [
            failure_stage
        ]

    # The database must return to its
    # original state after every failure.

    assert_fine_transaction_rolled_back(
        original
    )

    # Retry after restoring the dependencies.

    fresh_service = LoanService()

    loan = fresh_service.return_book(
        actor_id,
        loan_id
    )

    assert loan.status == "RETURNED"

    assert loan.returned_at is not None

    assert loan.copy.status == "AVAILABLE"

    assert loan.fine is not None

    assert loan.fine.amount == Decimal("6.00")

    assert loan.fine.status == "UNPAID"

    assert Fine.query.count() == (
        original["fine_count"] + 1
    )

    assert Payment.query.count() == (
        original["payment_count"]
    )

    assert get_audit_count(
        "FINE_CREATED"
    ) == original["fine_audit_count"] + 1

    assert get_audit_count(
        "LOAN_RETURNED"
    ) == original["return_audit_count"] + 1


# ==========================================
# COMMIT FAILURE PROTECTION
# ==========================================

def test_fine_transaction_commit_failure(
    loan_service,
    data,
    overdue_loan,
    monkeypatch
):

    actor_id = data["librarian"].id

    loan_id = overdue_loan.id

    original = capture_fine_transaction_state(
        overdue_loan
    )

    commit_calls = []

    def failing_commit():

        commit_calls.append(True)

        # Flush all pending changes,
        # but do not commit the transaction.

        db.session.flush()

        assert Fine.query.count() == 1

        assert get_audit_count(
            "FINE_CREATED"
        ) == 1

        assert get_audit_count(
            "LOAN_RETURNED"
        ) == 1

        raise SQLAlchemyError(
            "Simulated commit failure"
        )

    with monkeypatch.context() as patch:

        patch.setattr(
            db.session,
            "commit",
            failing_commit
        )

        with pytest.raises(DatabaseError):

            loan_service.return_book(
                actor_id,
                loan_id
            )

        assert commit_calls == [True]

    assert_fine_transaction_rolled_back(
        original
    )

    fresh_service = LoanService()

    loan = fresh_service.return_book(
        actor_id,
        loan_id
    )

    assert loan.status == "RETURNED"

    assert loan.copy.status == "AVAILABLE"

    assert Fine.query.count() == 1

    assert loan.fine.amount == Decimal("6.00")

    assert get_audit_count(
        "FINE_CREATED"
    ) == 1

    assert get_audit_count(
        "LOAN_RETURNED"
    ) == 1


# ==========================================
# MULTIPLE FINE AUDIT RECORDS
# ==========================================

def test_fine_audit_multiple_records(
    data,
    multiple_fines
):

    actor_id = data["librarian"].id

    audits = AuditLog.query.filter_by(
        action="FINE_CREATED"
    ).all()

    assert len(audits) == 5

    for fine in multiple_fines["fines"]:

        expected_description = (
            f"Fine ID: {fine.id}; "
            f"Loan ID: {fine.loan_id}; "
            f"Amount: {fine.amount} PLN"
        )

        matching_audits = [
            audit
            for audit in audits
            if audit.description == (
                expected_description
            )
        ]

        assert len(matching_audits) == 1

        audit = matching_audits[0]

        assert audit.user_id == actor_id

        assert audit.created_at is not None

        assert audit.created_at.tzinfo is None

    assert get_audit_count(
        "LOAN_RETURNED"
    ) == 5

    assert Fine.query.count() == 5


# ==========================================
# COMMITTED TRANSACTION PERSISTENCE
# ==========================================

def test_fine_committed_transaction_persistence(
    loan_service,
    data,
    overdue_loan
):

    actor_id = data["librarian"].id

    loan = loan_service.return_book(
        actor_id,
        overdue_loan.id
    )

    loan_id = loan.id

    copy_id = loan.copy_id

    fine_id = loan.fine.id

    returned_at = loan.returned_at

    audit = AuditLog.query.filter_by(
        action="FINE_CREATED"
    ).one()

    audit_id = audit.id

    # Rolling back a subsequent transaction
    # must not remove committed records.

    db.session.rollback()

    db.session.remove()

    saved_loan = db.session.get(
        Loan,
        loan_id
    )

    saved_copy = db.session.get(
        Copy,
        copy_id
    )

    saved_fine = db.session.get(
        Fine,
        fine_id
    )

    saved_audit = db.session.get(
        AuditLog,
        audit_id
    )

    assert saved_loan.status == "RETURNED"

    assert saved_loan.returned_at == returned_at

    assert saved_copy.status == "AVAILABLE"

    assert saved_fine.loan_id == loan_id

    assert saved_fine.amount == Decimal("6.00")

    assert saved_fine.paid_amount == (
        Decimal("0.00")
    )

    assert saved_fine.status == "UNPAID"

    assert saved_audit.action == "FINE_CREATED"

    assert saved_audit.user_id == actor_id

    assert Fine.query.count() == 1

    assert Payment.query.count() == 0

    fresh_service = FineService()

    assert fresh_service.get_remaining_amount(
        actor_id,
        fine_id
    ) == Decimal("6.00")


# ==========================================
# INACTIVE STAFF TRANSACTION PROTECTION
# ==========================================

@pytest.mark.parametrize(
    "actor_key",
    ["admin", "librarian"]
)
def test_fine_inactive_staff_transaction(
    loan_service,
    data,
    overdue_loan,
    actor_key
):

    actor = data[actor_key]

    actor.is_active = False

    db.session.commit()

    actor_id = actor.id

    loan_id = overdue_loan.id

    original = capture_fine_transaction_state(
        overdue_loan
    )

    with pytest.raises(InactiveAccountError):

        loan_service.return_book(
            actor_id,
            loan_id
        )

    assert_fine_transaction_rolled_back(
        original
    )