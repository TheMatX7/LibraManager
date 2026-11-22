
from decimal import Decimal

from app.extensions import db

from app.models import Payment

from app.repositories import (
    PaymentRepository,
    FineRepository
)

from app.services.base_service import BaseService
from app.services.auth_service import AuthService
from app.services.audit_service import AuditService
from app.services.reader_service import ReaderService
from app.services.fine_service import FineService

from app.exceptions import (
    ValidationError,
    BusinessRuleError,
    NotFoundError,
    AuthorizationError,
    InvalidPaymentError
)


class PaymentService(BaseService):
    """Service responsible for library financial payments."""

    VALID_METHODS = (
        "CASH",
        "CARD"
    )

    ZERO = FineService.ZERO

    MONEY_PRECISION = FineService.MONEY_PRECISION

    MAX_AMOUNT = FineService.MAX_AMOUNT

    # ==========================================
    # INITIALIZATION
    # ==========================================

    def __init__(self):

        self.repository = PaymentRepository()

        self.fine_repository = FineRepository()

        self.auth_service = AuthService()

        self.audit_service = AuditService()

        self.reader_service = ReaderService()

        self.fine_service = FineService()

        # Share dependencies with FineService.

        self.fine_service.repository = (
            self.fine_repository
        )

        self.fine_service.payment_repository = (
            self.repository
        )

        self.fine_service.auth_service = (
            self.auth_service
        )

        self.fine_service.audit_service = (
            self.audit_service
        )

        self.fine_service.reader_service = (
            self.reader_service
        )

    # ==========================================
    # VALIDATION
    # ==========================================

    def validate_id(
        self,
        value,
        field_name
    ):

        return self.fine_service.validate_id(
            value,
            field_name
        )

    def validate_amount(self, value):

        return self.fine_service.validate_amount(
            value,
            allow_zero=False
        )

    def validate_method(self, method):

        method = self.require_text(
            method,
            "Payment method"
        ).upper()

        if method not in self.VALID_METHODS:

            raise ValidationError(
                "Invalid payment method."
            )

        return method

    # ==========================================
    # INTERNAL OBJECT ACCESS
    # ==========================================

    def _get_payment(self, payment_id):

        self.validate_id(
            payment_id,
            "payment"
        )

        return self.require_exists(
            self.repository.get_by_id(
                payment_id
            ),
            "Payment not found."
        )

    def _get_fine(self, fine_id):

        self.validate_id(
            fine_id,
            "fine"
        )

        return self.require_exists(
            self.fine_repository.get_by_id(
                fine_id
            ),
            "Fine not found."
        )

    # ==========================================
    # PAYMENT BUSINESS RULES
    # ==========================================

    def _ensure_payment_allowed(
        self,
        fine,
        amount
    ):

        self.fine_service._ensure_consistency(
            fine
        )

        amount = self.validate_amount(
            amount
        )

        if fine.status == "PAID":

            raise InvalidPaymentError(
                "Fine is already fully paid."
            )

        remaining = (
            fine.amount - fine.paid_amount
        ).quantize(
            self.MONEY_PRECISION
        )

        if remaining <= self.ZERO:

            raise InvalidPaymentError(
                "Fine has no outstanding balance."
            )

        if amount > remaining:

            raise InvalidPaymentError(
                "Payment exceeds outstanding balance."
            )

    # ==========================================
    # PAYMENT CONSISTENCY
    # ==========================================

    def _ensure_payment_consistency(
        self,
        payment
    ):

        try:

            self.validate_amount(
                payment.amount
            )

        except ValidationError as error:

            raise BusinessRuleError(
                "Payment contains invalid amount."
            ) from error

        if payment.method not in self.VALID_METHODS:

            raise BusinessRuleError(
                "Payment contains invalid method."
            )

        if payment.paid_at is None:

            raise BusinessRuleError(
                "Payment has no payment date."
            )

        if payment.fine is None:

            raise BusinessRuleError(
                "Payment has no associated fine."
            )

        self.fine_service._ensure_consistency(
            payment.fine
        )

        return payment

    # ==========================================
    # FINANCIAL STATUS CALCULATION
    # ==========================================

    def _calculate_new_status(
        self,
        amount,
        paid_amount
    ):

        amount = self.fine_service.validate_amount(
            amount,
            allow_zero=False
        )

        paid_amount = (
            self.fine_service.validate_amount(
                paid_amount
            )
        )

        if paid_amount > amount:

            raise InvalidPaymentError(
                "Paid amount exceeds fine amount."
            )

        if paid_amount == self.ZERO:

            return "UNPAID"

        if paid_amount == amount:

            return "PAID"

        return "PARTIALLY_PAID"

    # ==========================================
    # ATOMIC FINE UPDATE
    # ==========================================

    def _update_fine_atomically(
        self,
        fine,
        amount
    ):

        """
        Update a fine within the caller's transaction.

        The caller must register the corresponding
        payment and commit both changes together.

        This method does not commit independently.
        """

        amount = self.validate_amount(
            amount
        )

        self._ensure_payment_allowed(
            fine,
            amount
        )

        previous_amount = fine.amount

        previous_paid_amount = fine.paid_amount

        previous_status = fine.status

        new_paid_amount = (
            previous_paid_amount + amount
        ).quantize(
            self.MONEY_PRECISION
        )

        new_status = self._calculate_new_status(
            previous_amount,
            new_paid_amount
        )

        updated = (
            self.fine_repository.update_payment_state(
                fine_id=fine.id,
                expected_amount=previous_amount,
                expected_paid_amount=previous_paid_amount,
                expected_status=previous_status,
                new_paid_amount=new_paid_amount,
                new_status=new_status
            )
        )

        if not updated:

            raise InvalidPaymentError(
                "Fine was modified concurrently. "
                "Refresh and retry."
            )

        db.session.refresh(fine)

        return fine




    # ==========================================
    # INTERNAL PAYMENT REGISTRATION
    # ==========================================

    def _register_payment(
        self,
        actor_id,
        fine,
        amount,
        method
    ):

        """
        Register a payment within the caller's transaction.

        The fine update, payment record and audit records
        must be committed together.
        """

        self.auth_service.require_staff(
            actor_id
        )

        amount = self.validate_amount(
            amount
        )

        method = self.validate_method(
            method
        )

        # Update financial state using optimistic
        # concurrency control.

        fine = self._update_fine_atomically(
            fine,
            amount
        )

        # Register the corresponding payment.

        payment = Payment(
            fine_id=fine.id,
            amount=amount,
            method=method
        )

        self.repository.add(
            payment
        )

        db.session.flush()

        # Verify that the payment records and fine
        # financial state are consistent.

        self._ensure_payment_consistency(
            payment
        )

        remaining_amount = (
            fine.amount - fine.paid_amount
        ).quantize(
            self.MONEY_PRECISION
        )

        # Register every successful payment.

        self.audit_service.log(
            action="PAYMENT_REGISTERED",
            user_id=actor_id,
            description=(
                f"Payment ID: {payment.id}; "
                f"Fine ID: {fine.id}; "
                f"Amount: {amount} PLN; "
                f"Method: {method}; "
                f"Remaining amount: "
                f"{remaining_amount} PLN; "
                f"Status: {fine.status}"
            )
        )

        # Register an additional event when a fine
        # becomes fully paid.

        if fine.status == "PAID":

            self.audit_service.log(
                action="FINE_PAID",
                user_id=actor_id,
                description=(
                    f"Fine ID: {fine.id}; "
                    f"Payment ID: {payment.id}; "
                    f"Total amount: {fine.amount} PLN; "
                    f"Paid amount: "
                    f"{fine.paid_amount} PLN"
                )
            )

        return payment

    # ==========================================
    # PUBLIC PAYMENT REGISTRATION
    # ==========================================

    def register_payment(
        self,
        actor_id,
        fine_id,
        amount,
        method
    ):

        """
        Register a partial or complete payment.

        Only active administrators and librarians
        are permitted to register payments.
        """

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            self.validate_id(
                fine_id,
                "fine"
            )

            amount = self.validate_amount(
                amount
            )

            method = self.validate_method(
                method
            )

            fine = self._get_fine(
                fine_id
            )

            payment = self._register_payment(
                actor_id,
                fine,
                amount,
                method
            )

            return payment

    # ==========================================
    # FULL FINE PAYMENT
    # ==========================================

    def pay_full_fine(
        self,
        actor_id,
        fine_id,
        method
    ):

        """
        Register a payment covering the entire
        remaining balance of a fine.
        """

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            self.validate_id(
                fine_id,
                "fine"
            )

            method = self.validate_method(
                method
            )

            fine = self._get_fine(
                fine_id
            )

            self.fine_service._ensure_consistency(
                fine
            )

            if fine.status == "PAID":

                raise InvalidPaymentError(
                    "Fine is already fully paid."
                )

            remaining_amount = (
                fine.amount - fine.paid_amount
            ).quantize(
                self.MONEY_PRECISION
            )

            if remaining_amount <= self.ZERO:

                raise InvalidPaymentError(
                    "Fine has no outstanding balance."
                )

            payment = self._register_payment(
                actor_id,
                fine,
                remaining_amount,
                method
            )

            return payment

    # ==========================================
    # READ OPERATIONS
    # ==========================================

    def get_by_id(
        self,
        actor_id,
        payment_id
    ):

        """Return one payment while enforcing payment-history isolation."""

        user = self.auth_service.get_current_user(
            actor_id
        )

        self.validate_id(
            payment_id,
            "payment"
        )

        payment = self.repository.get_by_id(
            payment_id
        )

        # A reader must not be able to use record existence as an
        # oracle for another reader's financial history.
        if payment is None:

            if user.role == "READER":

                raise AuthorizationError(
                    "Access denied."
                )

            raise NotFoundError(
                "Payment not found."
            )

        self.auth_service.require_reader_access(
            actor_id,
            payment.fine.loan.reader_id
        )

        return self._ensure_payment_consistency(
            payment
        )

    def get_by_fine(
        self,
        actor_id,
        fine_id
    ):

        """Return the payment history for a fine visible to ``actor_id``."""

        fine = self.fine_service.get_by_id(
            actor_id,
            fine_id
        )

        payments = self.repository.get_by_fine(
            fine.id
        )

        for payment in payments:

            self._ensure_payment_consistency(
                payment
            )

        return payments

    def get_by_reader(
        self,
        actor_id,
        reader_id
    ):

        """Return payment history for a reader, subject to RBAC/IDOR checks."""

        self.validate_id(
            reader_id,
            "reader"
        )

        self.auth_service.require_reader_access(
            actor_id,
            reader_id
        )

        payments = self.repository.get_by_reader(
            reader_id
        )

        for payment in payments:

            self._ensure_payment_consistency(
                payment
            )

        return payments

    def get_all(self, actor_id):

        self.auth_service.require_staff(actor_id)

        payments = self.repository.get_all()

        for payment in payments:

            self._ensure_payment_consistency(
                payment
            )

        return payments

    def get_by_method(
        self,
        actor_id,
        method
    ):

        self.auth_service.require_staff(actor_id)

        method = self.validate_method(method)

        payments = self.repository.get_by_method(method)

        for payment in payments:

            self._ensure_payment_consistency(
                payment
            )

        return payments

    # ==========================================
    # READER PROFILE
    # ==========================================

    def get_own_payments(self, actor_id):

        reader = self.reader_service.get_own_profile(
            actor_id
        )

        return self.get_by_reader(
            actor_id,
            reader.id
        )

    def get_own_payments_by_method(
        self,
        actor_id,
        method
    ):

        method = self.validate_method(method)

        return [
            payment
            for payment in self.get_own_payments(actor_id)
            if payment.method == method
        ]

    # ==========================================
    # PAYMENT TOTALS
    # ==========================================

    def get_total_by_fine(
        self,
        actor_id,
        fine_id
    ):

        fine = self.fine_service.get_by_id(
            actor_id,
            fine_id
        )

        self.fine_service._ensure_consistency(fine)

        return self.repository.get_total_by_fine(
            fine.id
        ).quantize(self.MONEY_PRECISION)

    def get_total_by_reader(
        self,
        actor_id,
        reader_id
    ):

        self.validate_id(
            reader_id,
            "reader"
        )

        self.auth_service.require_reader_access(
            actor_id,
            reader_id
        )

        return self.repository.get_total_by_reader(
            reader_id
        ).quantize(self.MONEY_PRECISION)

    def get_own_total_payments(self, actor_id):

        reader = self.reader_service.get_own_profile(
            actor_id
        )

        return self.get_total_by_reader(
            actor_id,
            reader.id
        )

    def get_total_payments(self, actor_id):

        self.auth_service.require_staff(actor_id)

        return self.repository.get_total_payments().quantize(
            self.MONEY_PRECISION
        )

    def get_total_by_method(
        self,
        actor_id,
        method
    ):

        self.auth_service.require_staff(actor_id)

        method = self.validate_method(method)

        return self.repository.get_total_by_method(
            method
        ).quantize(self.MONEY_PRECISION)

    # ==========================================
    # PAYMENT SUMMARIES
    # ==========================================

    def _build_summary(self, payments):

        """Build a Decimal-safe, read-only payment summary."""

        summary = {
            "total_payments": 0,
            "cash_payments": 0,
            "card_payments": 0,
            "total_amount": self.ZERO,
            "cash_total": self.ZERO,
            "card_total": self.ZERO
        }

        for payment in payments:

            self._ensure_payment_consistency(payment)

            summary["total_payments"] += 1
            summary["total_amount"] += payment.amount

            if payment.method == "CASH":

                summary["cash_payments"] += 1
                summary["cash_total"] += payment.amount

            else:

                summary["card_payments"] += 1
                summary["card_total"] += payment.amount

        for key in (
            "total_amount",
            "cash_total",
            "card_total"
        ):

            summary[key] = summary[key].quantize(
                self.MONEY_PRECISION
            )

        return summary

    def get_summary(self, actor_id):

        self.auth_service.require_staff(actor_id)

        return self._build_summary(
            self.repository.get_all()
        )

    def get_reader_summary(
        self,
        actor_id,
        reader_id
    ):

        payments = self.get_by_reader(
            actor_id,
            reader_id
        )

        summary = self._build_summary(payments)
        summary["reader_id"] = reader_id

        return summary

    def get_own_summary(self, actor_id):

        reader = self.reader_service.get_own_profile(
            actor_id
        )

        return self.get_reader_summary(
            actor_id,
            reader.id
        )

    def count(self, actor_id):

        self.auth_service.require_staff(actor_id)

        return self.repository.count()

