from datetime import UTC, datetime, timedelta
from decimal import Decimal
from queue import Queue
from threading import Barrier, Thread

import pytest

from app.exceptions import (
    AuthorizationError,
    BusinessRuleError,
    DatabaseError,
    InvalidPaymentError,
    NotFoundError,
    ValidationError
)
from app.extensions import db
from app.models import (
    AuditLog,
    Book,
    Copy,
    Fine,
    Loan,
    Payment,
    Reader,
    User
)
from app import create_app
from app.services import PaymentService


@pytest.fixture
def payment_context(app):
    """Create only the persisted relationships required by PaymentService."""

    now = datetime.now(UTC).replace(tzinfo=None)

    staff = User(
        username="payment_service_staff",
        email="payment-service-staff@example.test",
        password_hash="not-used-by-these-tests",
        role="LIBRARIAN",
        is_active=True
    )
    reader_user = User(
        username="payment_service_reader",
        email="payment-service-reader@example.test",
        password_hash="not-used-by-these-tests",
        role="READER",
        is_active=True
    )
    other_reader_user = User(
        username="payment_service_other_reader",
        email="payment-service-other-reader@example.test",
        password_hash="not-used-by-these-tests",
        role="READER",
        is_active=True
    )

    db.session.add_all([staff, reader_user, other_reader_user])
    db.session.flush()

    reader = Reader(
        user_id=reader_user.id,
        card_number="PAYMENT-SERVICE-001",
        first_name="Jan",
        last_name="Kowalski"
    )
    other_reader = Reader(
        user_id=other_reader_user.id,
        card_number="PAYMENT-SERVICE-002",
        first_name="Anna",
        last_name="Nowak"
    )
    book = Book(title="Payment service test book")

    db.session.add_all([reader, other_reader, book])
    db.session.flush()

    first_copy = Copy(
        book_id=book.id,
        inventory_number="PAYMENT-SERVICE-COPY-001"
    )
    second_copy = Copy(
        book_id=book.id,
        inventory_number="PAYMENT-SERVICE-COPY-002"
    )

    db.session.add_all([first_copy, second_copy])
    db.session.flush()

    first_loan = Loan(
        copy_id=first_copy.id,
        reader_id=reader.id,
        due_date=now - timedelta(days=2),
        returned_at=now - timedelta(days=1),
        status="RETURNED"
    )
    second_loan = Loan(
        copy_id=second_copy.id,
        reader_id=reader.id,
        due_date=now - timedelta(days=4),
        returned_at=now - timedelta(days=1),
        status="RETURNED"
    )

    db.session.add_all([first_loan, second_loan])
    db.session.flush()

    first_fine = Fine(
        loan_id=first_loan.id,
        amount=Decimal("10.00"),
        paid_amount=Decimal("0.00"),
        status="UNPAID"
    )
    second_fine = Fine(
        loan_id=second_loan.id,
        amount=Decimal("20.00"),
        paid_amount=Decimal("0.00"),
        status="UNPAID"
    )

    db.session.add_all([first_fine, second_fine])
    db.session.commit()

    return {
        "staff_id": staff.id,
        "reader_user_id": reader_user.id,
        "other_reader_user_id": other_reader_user.id,
        "reader_id": reader.id,
        "other_reader_id": other_reader.id,
        "first_fine_id": first_fine.id,
        "second_fine_id": second_fine.id
    }


def test_register_partial_and_full_payment_with_audit(payment_context):
    service = PaymentService()

    partial_payment = service.register_payment(
        payment_context["staff_id"],
        payment_context["first_fine_id"],
        Decimal("4.00"),
        " cash "
    )

    first_fine = db.session.get(
        Fine,
        payment_context["first_fine_id"]
    )

    assert partial_payment.method == "CASH"
    assert first_fine.amount == Decimal("10.00")
    assert first_fine.paid_amount == Decimal("4.00")
    assert first_fine.status == "PARTIALLY_PAID"
    assert [log.action for log in AuditLog.query.all()] == [
        "PAYMENT_REGISTERED"
    ]

    final_payment = service.pay_full_fine(
        payment_context["staff_id"],
        payment_context["first_fine_id"],
        "card"
    )

    db.session.refresh(first_fine)

    assert final_payment.amount == Decimal("6.00")
    assert final_payment.method == "CARD"
    assert first_fine.amount == Decimal("10.00")
    assert first_fine.paid_amount == Decimal("10.00")
    assert first_fine.status == "PAID"
    assert [log.action for log in AuditLog.query.order_by(AuditLog.id)] == [
        "PAYMENT_REGISTERED",
        "PAYMENT_REGISTERED",
        "FINE_PAID"
    ]


def test_payment_history_totals_and_summaries(payment_context):
    service = PaymentService()
    staff_id = payment_context["staff_id"]
    first_fine_id = payment_context["first_fine_id"]
    second_fine_id = payment_context["second_fine_id"]
    reader_id = payment_context["reader_id"]

    first_payment = service.register_payment(
        staff_id, first_fine_id, "4.00", "cash"
    )
    second_payment = service.pay_full_fine(
        staff_id, first_fine_id, "CARD"
    )
    service.register_payment(
        staff_id, second_fine_id, "8.00", "CARD"
    )

    assert service.get_by_id(staff_id, first_payment.id).id == first_payment.id
    assert [payment.id for payment in service.get_by_fine(
        staff_id, first_fine_id
    )] == [first_payment.id, second_payment.id]
    assert len(service.get_by_reader(staff_id, reader_id)) == 3
    assert len(service.get_all(staff_id)) == 3
    assert len(service.get_by_method(staff_id, "card")) == 2
    assert service.get_total_by_fine(staff_id, first_fine_id) == Decimal("10.00")
    assert service.get_total_by_reader(staff_id, reader_id) == Decimal("18.00")
    assert service.get_total_payments(staff_id) == Decimal("18.00")
    assert service.get_total_by_method(staff_id, "cash") == Decimal("4.00")
    assert service.get_total_by_method(staff_id, "card") == Decimal("14.00")
    assert service.count(staff_id) == 3

    summary = service.get_summary(staff_id)
    reader_summary = service.get_reader_summary(staff_id, reader_id)

    assert summary == {
        "total_payments": 3,
        "cash_payments": 1,
        "card_payments": 2,
        "total_amount": Decimal("18.00"),
        "cash_total": Decimal("4.00"),
        "card_total": Decimal("14.00")
    }
    assert reader_summary == {**summary, "reader_id": reader_id}


def test_reader_can_only_view_own_payment_history(payment_context):
    service = PaymentService()
    staff_id = payment_context["staff_id"]
    reader_user_id = payment_context["reader_user_id"]
    other_reader_user_id = payment_context["other_reader_user_id"]
    reader_id = payment_context["reader_id"]

    payment = service.register_payment(
        staff_id,
        payment_context["first_fine_id"],
        "4.00",
        "CASH"
    )

    assert service.get_by_id(reader_user_id, payment.id).id == payment.id
    assert [item.id for item in service.get_own_payments(
        reader_user_id
    )] == [payment.id]
    assert [item.id for item in service.get_own_payments_by_method(
        reader_user_id, "cash"
    )] == [payment.id]
    assert service.get_own_total_payments(reader_user_id) == Decimal("4.00")
    assert service.get_own_summary(reader_user_id) == {
        "total_payments": 1,
        "cash_payments": 1,
        "card_payments": 0,
        "total_amount": Decimal("4.00"),
        "cash_total": Decimal("4.00"),
        "card_total": Decimal("0.00"),
        "reader_id": reader_id
    }

    with pytest.raises(AuthorizationError):
        service.get_by_id(other_reader_user_id, payment.id)

    with pytest.raises(AuthorizationError):
        service.get_by_id(reader_user_id, 999999)

    with pytest.raises(AuthorizationError):
        service.get_by_reader(other_reader_user_id, reader_id)

    with pytest.raises(AuthorizationError):
        service.get_all(reader_user_id)

    with pytest.raises(AuthorizationError):
        service.register_payment(
            reader_user_id,
            payment_context["first_fine_id"],
            "1.00",
            "CASH"
        )


@pytest.mark.parametrize(
    "amount",
    [True, 1.0, 0, "0.001", "-1.00", "Infinity", "NaN", "100000000.00"]
)
def test_payment_amount_validation_rejects_unsafe_values(
    payment_context,
    amount
):
    service = PaymentService()

    with pytest.raises(ValidationError):
        service.register_payment(
            payment_context["staff_id"],
            payment_context["first_fine_id"],
            amount,
            "CASH"
        )


@pytest.mark.parametrize("method", [None, "", "transfer", True])
def test_payment_method_validation(payment_context, method):
    service = PaymentService()

    with pytest.raises(ValidationError):
        service.register_payment(
            payment_context["staff_id"],
            payment_context["first_fine_id"],
            "1.00",
            method
        )


def test_overpayment_and_repeated_full_payment_are_rejected(payment_context):
    service = PaymentService()
    staff_id = payment_context["staff_id"]
    fine_id = payment_context["first_fine_id"]

    with pytest.raises(InvalidPaymentError):
        service.register_payment(staff_id, fine_id, "10.01", "CASH")

    service.pay_full_fine(staff_id, fine_id, "CASH")

    with pytest.raises(InvalidPaymentError):
        service.pay_full_fine(staff_id, fine_id, "CASH")

    assert db.session.get(Fine, fine_id).paid_amount == Decimal("10.00")
    assert service.count(staff_id) == 1


def test_failed_audit_rolls_back_the_fine_and_payment(
    payment_context,
    monkeypatch
):
    service = PaymentService()
    fine_id = payment_context["first_fine_id"]

    def fail_payment_audit(action, *args, **kwargs):
        if action == "PAYMENT_REGISTERED":
            raise RuntimeError("audit storage failed")

    monkeypatch.setattr(service.audit_service, "log", fail_payment_audit)

    with pytest.raises(RuntimeError, match="audit storage failed"):
        service.register_payment(
            payment_context["staff_id"],
            fine_id,
            "4.00",
            "CASH"
        )

    db.session.expire_all()
    fine = db.session.get(Fine, fine_id)

    assert fine.paid_amount == Decimal("0.00")
    assert fine.status == "UNPAID"
    assert service.count(payment_context["staff_id"]) == 0
    assert AuditLog.query.count() == 0


def test_payment_internal_integrity_guards(payment_context):
    """Exercise corruption guards that public database constraints normally prevent."""

    service = PaymentService()
    staff_id = payment_context["staff_id"]
    fine_id = payment_context["first_fine_id"]

    with pytest.raises(NotFoundError, match="Payment not found"):
        service._get_payment(999999)

    with pytest.raises(NotFoundError, match="Fine not found"):
        service._get_fine(999999)

    assert service._calculate_new_status("10.00", "0.00") == "UNPAID"
    assert service._calculate_new_status("10.00", "4.00") == "PARTIALLY_PAID"
    assert service._calculate_new_status("10.00", "10.00") == "PAID"

    with pytest.raises(InvalidPaymentError):
        service._calculate_new_status("10.00", "10.01")

    invalid_amount = Payment(amount=Decimal("0.00"), method="CASH")
    with pytest.raises(BusinessRuleError, match="invalid amount"):
        service._ensure_payment_consistency(invalid_amount)

    invalid_method = Payment(
        amount=Decimal("1.00"),
        method="TRANSFER",
        paid_at=datetime.now(UTC).replace(tzinfo=None)
    )
    with pytest.raises(BusinessRuleError, match="invalid method"):
        service._ensure_payment_consistency(invalid_method)

    missing_date = Payment(amount=Decimal("1.00"), method="CASH")
    with pytest.raises(BusinessRuleError, match="no payment date"):
        service._ensure_payment_consistency(missing_date)

    missing_fine = Payment(
        amount=Decimal("1.00"),
        method="CASH",
        paid_at=datetime.now(UTC).replace(tzinfo=None)
    )
    with pytest.raises(BusinessRuleError, match="no associated fine"):
        service._ensure_payment_consistency(missing_fine)

    service.pay_full_fine(staff_id, fine_id, "CASH")
    paid_fine = db.session.get(Fine, fine_id)

    with pytest.raises(InvalidPaymentError, match="already fully paid"):
        service._ensure_payment_allowed(paid_fine, Decimal("1.00"))

    with pytest.raises(NotFoundError, match="Payment not found"):
        service.get_by_id(staff_id, 999999)


def test_concurrent_payment_attempts_never_create_a_double_payment(tmp_path):
    """Exercise optimistic locking through two independent SQLite sessions.

    SQLite may report a write lock instead of the stale-state result, depending
    on which worker upgrades its read transaction first.  Both outcomes are a
    safe rejection: the operation is deliberately not retried automatically.
    """

    database_path = tmp_path / "payment-concurrency.sqlite"
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "payment-concurrency-test-key",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "connect_args": {"timeout": 5}
        }
    })

    try:
        with application.app_context():
            now = datetime.now(UTC).replace(tzinfo=None)
            staff = User(
                username="concurrent_payment_staff",
                email="concurrent-payment-staff@example.test",
                password_hash="not-used",
                role="LIBRARIAN",
                is_active=True
            )
            reader_user = User(
                username="concurrent_payment_reader",
                email="concurrent-payment-reader@example.test",
                password_hash="not-used",
                role="READER",
                is_active=True
            )
            db.session.add_all([staff, reader_user])
            db.session.flush()

            reader = Reader(
                user_id=reader_user.id,
                card_number="CONCURRENT-PAYMENT-READER",
                first_name="Jan",
                last_name="Kowalski"
            )
            book = Book(title="Concurrent payment test book")
            db.session.add_all([reader, book])
            db.session.flush()

            copy = Copy(
                book_id=book.id,
                inventory_number="CONCURRENT-PAYMENT-COPY"
            )
            db.session.add(copy)
            db.session.flush()

            loan = Loan(
                copy_id=copy.id,
                reader_id=reader.id,
                due_date=now - timedelta(days=2),
                returned_at=now - timedelta(days=1),
                status="RETURNED"
            )
            db.session.add(loan)
            db.session.flush()

            fine = Fine(
                loan_id=loan.id,
                amount=Decimal("10.00"),
                paid_amount=Decimal("0.00"),
                status="UNPAID"
            )
            db.session.add(fine)
            db.session.commit()

            staff_id = staff.id
            fine_id = fine.id

        barrier = Barrier(2)
        outcomes = Queue()

        def attempt(method):
            with application.app_context():
                service = PaymentService()
                fine = service._get_fine(fine_id)

                # Both isolated scoped sessions hold the same snapshot before
                # attempting the conditional UPDATE.
                barrier.wait(timeout=10)

                try:
                    with service.transaction():
                        service._register_payment(
                            staff_id,
                            fine,
                            Decimal("10.00"),
                            method
                        )
                    outcomes.put("success")
                except (InvalidPaymentError, DatabaseError):
                    outcomes.put("rejected")

        workers = [
            Thread(target=attempt, args=("CASH",)),
            Thread(target=attempt, args=("CARD",))
        ]

        for worker in workers:
            worker.start()

        for worker in workers:
            worker.join(timeout=15)
            assert not worker.is_alive()

        assert sorted(outcomes.get_nowait() for _ in workers) == [
            "rejected",
            "success"
        ]

        with application.app_context():
            db.session.expire_all()
            fine = db.session.get(Fine, fine_id)

            assert fine.paid_amount == Decimal("10.00")
            assert fine.status == "PAID"
            assert len(PaymentService().get_by_fine(staff_id, fine_id)) == 1

    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()
            db.session.remove()
            db.engine.dispose()
