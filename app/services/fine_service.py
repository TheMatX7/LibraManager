from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.models import Fine

from app.repositories import (
    FineRepository,
    LoanRepository,
    PaymentRepository
)

from app.services.base_service import BaseService
from app.services.auth_service import AuthService
from app.services.audit_service import AuditService
from app.services.reader_service import ReaderService
from app.services.setting_service import SettingService

from app.exceptions import (
    ValidationError,
    BusinessRuleError,
    NotFoundError,
    AuthorizationError
)


class FineService(BaseService):
    """Service responsible for library financial fines."""

    VALID_STATUSES = (
        "UNPAID",
        "PARTIALLY_PAID",
        "PAID"
    )

    ZERO = Decimal("0.00")

    MONEY_PRECISION = Decimal("0.01")

    MAX_AMOUNT = Decimal("99999999.99")

    def __init__(self):

        self.repository = FineRepository()

        self.loan_repository = LoanRepository()
        self.payment_repository = PaymentRepository()

        self.auth_service = AuthService()
        self.audit_service = AuditService()

        self.reader_service = ReaderService()
        self.setting_service = SettingService()


    # ==========================================
    # VALIDATION
    # ==========================================

    def validate_id(self, value, field_name):

        if type(value) is not int or value < 1:

            raise ValidationError(
                f"Invalid {field_name} identifier."
            )

        return value


    def validate_status(self, status):

        status = self.require_text(
            status,
            "Status"
        ).upper()

        if status not in self.VALID_STATUSES:

            raise ValidationError(
                "Invalid fine status."
            )

        return status


    def validate_amount(
        self,
        value,
        allow_zero=True
    ):

        if type(allow_zero) is not bool:

            raise ValidationError(
                "Invalid zero amount option."
            )

        if isinstance(value, bool):

            raise ValidationError(
                "Invalid monetary amount."
            )

        if not isinstance(
            value,
            (Decimal, int, str)
        ):

            raise ValidationError(
                "Invalid monetary amount."
            )

        try:

            amount = Decimal(str(value))

            if not amount.is_finite():

                raise ValueError()

            if amount < self.ZERO:

                raise ValueError()

            if amount > self.MAX_AMOUNT:

                raise ValueError()

            normalized = amount.quantize(
                self.MONEY_PRECISION
            )

            if normalized != amount:

                raise ValueError()

            if not allow_zero and amount == self.ZERO:

                raise ValueError()

            if normalized == self.ZERO:

                return self.ZERO

            return normalized

        except (
            InvalidOperation,
            ValueError,
            TypeError
        ) as error:

            raise ValidationError(
                "Invalid monetary amount."
            ) from error


    # ==========================================
    # INTERNAL OBJECT ACCESS
    # ==========================================

    def _get_fine(self, fine_id):

        self.validate_id(
            fine_id,
            "fine"
        )

        return self.require_exists(
            self.repository.get_by_id(fine_id),
            "Fine not found."
        )


    def _get_loan(self, loan_id):

        self.validate_id(
            loan_id,
            "loan"
        )

        return self.require_exists(
            self.loan_repository.get_by_id(
                loan_id
            ),
            "Loan not found."
        )


    # ==========================================
    # FINANCIAL CONSISTENCY
    # ==========================================

    def _ensure_consistency(self, fine):

        try:

            amount = self.validate_amount(
                fine.amount,
                allow_zero=False
            )

            paid_amount = self.validate_amount(
                fine.paid_amount
            )

        except ValidationError as error:

            raise BusinessRuleError(
                "Fine contains invalid monetary values."
            ) from error

        if paid_amount > amount:

            raise BusinessRuleError(
                "Paid amount exceeds fine amount."
            )

        if fine.loan is None:

            raise BusinessRuleError(
                "Fine has no associated loan."
            )

        if fine.loan.status != "RETURNED":

            raise BusinessRuleError(
                "Fine belongs to a non-returned loan."
            )

        if fine.loan.returned_at is None:

            raise BusinessRuleError(
                "Returned loan has no return date."
            )

        if fine.loan.returned_at <= fine.loan.due_date:

            raise BusinessRuleError(
                "Fine belongs to a loan returned on time."
            )

        if paid_amount == self.ZERO:

            expected_status = "UNPAID"

        elif paid_amount == amount:

            expected_status = "PAID"

        else:

            expected_status = "PARTIALLY_PAID"

        if fine.status != expected_status:

            raise BusinessRuleError(
                "Fine status is inconsistent with "
                "the paid amount."
            )

        total_payments = self.ZERO

        payments = self.payment_repository.get_by_fine(
            fine.id
        )

        for payment in payments:

            try:

                payment_amount = self.validate_amount(
                    payment.amount,
                    allow_zero=False
                )

            except ValidationError as error:

                raise BusinessRuleError(
                    "Fine contains an invalid payment."
                ) from error

            total_payments += payment_amount

        if total_payments != paid_amount:

            raise BusinessRuleError(
                "Payment records are inconsistent "
                "with the fine paid amount."
            )

        return fine


    # ==========================================
    # FINE CALCULATIONS
    # ==========================================

    def calculate_fine_amount(
        self,
        overdue_days
    ):

        if (
            type(overdue_days) is not int
            or overdue_days < 0
        ):

            raise ValidationError(
                "Overdue days must be a non-negative integer."
            )

        daily_amount = (
            self.setting_service.get_fine_per_day()
        )

        if daily_amount == self.ZERO:

            return self.ZERO

        # Check the limit before multiplication.
        if overdue_days > (
            self.MAX_AMOUNT // daily_amount
        ):

            raise BusinessRuleError(
                "Calculated fine exceeds database limit."
            )

        amount = (
            Decimal(overdue_days) * daily_amount
        ).quantize(self.MONEY_PRECISION)

        return amount


    # ==========================================
    # INTERNAL FINE CREATION
    # ==========================================

    def _create_return_fine(
        self,
        actor_id,
        loan,
        overdue_days
    ):

        """
        Create a fine within the caller's transaction.

        This method must not commit or roll back
        independently of LoanService.
        """

        self.auth_service.require_staff(
            actor_id
        )

        if loan.id is None:

            raise BusinessRuleError(
                "Cannot create a fine for an unsaved loan."
            )

        if loan.status != "ACTIVE":

            raise BusinessRuleError(
                "Fine creation requires an active loan."
            )

        existing_fine = (
            self.repository.get_by_loan(
                loan.id
            )
        )

        if existing_fine is not None:

            raise BusinessRuleError(
                "Active loan already has a fine."
            )

        amount = self.calculate_fine_amount(
            overdue_days
        )

        if amount == self.ZERO:

            return None

        fine = Fine(
            loan_id=loan.id,
            amount=amount,
            paid_amount=self.ZERO,
            status="UNPAID"
        )

        self.repository.add(fine)

        db.session.flush()

        self.audit_service.log(
            action="FINE_CREATED",
            user_id=actor_id,
            description=(
                f"Fine ID: {fine.id}; "
                f"Loan ID: {loan.id}; "
                f"Amount: {amount} PLN"
            )
        )

        return fine


    # ==========================================
    # READ OPERATIONS
    # ==========================================

    def get_by_id(
        self,
        actor_id,
        fine_id
    ):

        user = self.auth_service.get_current_user(
            actor_id
        )

        self.validate_id(
            fine_id,
            "fine"
        )

        fine = self.repository.get_by_id(
            fine_id
        )

        if fine is None:

            if user.role == "READER":

                raise AuthorizationError(
                    "Access denied."
                )

            raise NotFoundError(
                "Fine not found."
            )

        self.auth_service.require_reader_access(
            actor_id,
            fine.loan.reader_id
        )

        return fine


    def get_by_loan(
        self,
        actor_id,
        loan_id
    ):

        user = self.auth_service.get_current_user(
            actor_id
        )

        self.validate_id(
            loan_id,
            "loan"
        )

        loan = self.loan_repository.get_by_id(
            loan_id
        )

        if loan is None:

            if user.role == "READER":

                raise AuthorizationError(
                    "Access denied."
                )

            raise NotFoundError(
                "Loan not found."
            )

        self.auth_service.require_reader_access(
            actor_id,
            loan.reader_id
        )

        return self.repository.get_by_loan(
            loan.id
        )


    def get_all(self, actor_id):

        self.auth_service.require_staff(
            actor_id
        )

        return self.repository.get_all()


    def get_by_reader(
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

        return self.repository.get_by_reader(
            reader_id
        )


    def get_by_status(
        self,
        actor_id,
        status
    ):

        self.auth_service.require_staff(
            actor_id
        )

        status = self.validate_status(
            status
        )

        return [
            fine
            for fine in self.repository.get_all()
            if fine.status == status
        ]


    def get_unpaid_fines(self, actor_id):

        self.auth_service.require_staff(
            actor_id
        )

        return self.repository.get_unpaid_fines()


    # ==========================================
    # READER PROFILE
    # ==========================================

    def get_own_fines(self, actor_id):

        reader = self.reader_service.get_own_profile(
            actor_id
        )

        return self.repository.get_by_reader(
            reader.id
        )


    def get_own_unpaid_fines(
        self,
        actor_id
    ):

        fines = self.get_own_fines(
            actor_id
        )

        return [
            fine
            for fine in fines
            if fine.status in (
                "UNPAID",
                "PARTIALLY_PAID"
            )
        ]


    # ==========================================
    # FINANCIAL BALANCES
    # ==========================================

    def get_remaining_amount(
        self,
        actor_id,
        fine_id
    ):

        fine = self.get_by_id(
            actor_id,
            fine_id
        )

        self._ensure_consistency(fine)

        return (
            fine.amount - fine.paid_amount
        ).quantize(self.MONEY_PRECISION)


    def get_total_unpaid_by_reader(
        self,
        actor_id,
        reader_id
    ):

        fines = self.get_by_reader(
            actor_id,
            reader_id
        )

        total = self.ZERO

        for fine in fines:

            self._ensure_consistency(fine)

            total += (
                fine.amount - fine.paid_amount
            )

        return total.quantize(
            self.MONEY_PRECISION
        )


    def get_own_total_unpaid(
        self,
        actor_id
    ):

        reader = self.reader_service.get_own_profile(
            actor_id
        )

        return self.get_total_unpaid_by_reader(
            actor_id,
            reader.id
        )


    # ==========================================
    # INTERNAL STATISTICS
    # ==========================================

    def _build_summary(self, fines):

        summary = {
            "total_fines": 0,
            "unpaid_fines": 0,
            "partially_paid_fines": 0,
            "paid_fines": 0,
            "total_amount": self.ZERO,
            "total_paid": self.ZERO,
            "total_unpaid": self.ZERO
        }

        for fine in fines:

            self._ensure_consistency(fine)

            summary["total_fines"] += 1

            summary["total_amount"] += (
                fine.amount
            )

            summary["total_paid"] += (
                fine.paid_amount
            )

            summary["total_unpaid"] += (
                fine.amount - fine.paid_amount
            )

            if fine.status == "UNPAID":

                summary["unpaid_fines"] += 1

            elif fine.status == "PARTIALLY_PAID":

                summary["partially_paid_fines"] += 1

            else:

                summary["paid_fines"] += 1

        for key in (
            "total_amount",
            "total_paid",
            "total_unpaid"
        ):

            summary[key] = summary[key].quantize(
                self.MONEY_PRECISION
            )

        return summary


    # ==========================================
    # PUBLIC STATISTICS
    # ==========================================

    def get_reader_summary(
        self,
        actor_id,
        reader_id
    ):

        fines = self.get_by_reader(
            actor_id,
            reader_id
        )

        summary = self._build_summary(
            fines
        )

        summary["reader_id"] = reader_id

        return summary


    def get_own_summary(
        self,
        actor_id
    ):

        reader = self.reader_service.get_own_profile(
            actor_id
        )

        return self.get_reader_summary(
            actor_id,
            reader.id
        )


    def get_summary(self, actor_id):

        self.auth_service.require_staff(
            actor_id
        )

        fines = self.repository.get_all()

        return self._build_summary(
            fines
        )


    def count(self, actor_id):

        self.auth_service.require_staff(
            actor_id
        )

        return self.repository.count()