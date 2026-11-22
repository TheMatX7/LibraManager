from datetime import datetime, timezone, timedelta
from decimal import Decimal

from app.extensions import db
from app.models import Loan, Fine

from app.repositories import (
    LoanRepository,
    CopyRepository,
    ReservationRepository,
    FineRepository
)

from app.services.base_service import BaseService
from app.services.auth_service import AuthService
from app.services.audit_service import AuditService
from app.services.reader_service import ReaderService
from app.services.setting_service import SettingService
from app.services.reservation_service import ReservationService
from app.services.fine_service import FineService

from app.exceptions import (
    ValidationError,
    BusinessRuleError,
    NotFoundError,
    CopyUnavailableError,
    LoanLimitExceededError,
    LoanAlreadyReturnedError,
    AuthorizationError
)


class LoanService(BaseService):
    """Service responsible for library loans and returns."""

    VALID_STATUSES = (
        "ACTIVE",
        "RETURNED",
        "CANCELLED"
    )

    def __init__(self):

        self.repository = LoanRepository()
        self.copy_repository = CopyRepository()
        self.reservation_repository = ReservationRepository()
        self.fine_repository = FineRepository()

        self.auth_service = AuthService()
        self.audit_service = AuditService()
        self.reader_service = ReaderService()
        self.setting_service = SettingService()
        self.reservation_service = ReservationService()
        self.fine_service = FineService()
        
        self.fine_service.repository = self.fine_repository
        self.fine_service.setting_service = self.setting_service
        self.fine_service.audit_service = self.audit_service
        self.fine_service.auth_service = self.auth_service

    # ==========================================
    # VALIDATION
    # ==========================================

    @staticmethod
    def now():

        return datetime.now(
            timezone.utc
        ).replace(tzinfo=None)

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
                "Invalid loan status."
            )

        return status

    # ==========================================
    # INTERNAL METHODS
    # ==========================================

    def _get_loan(self, loan_id):

        self.validate_id(loan_id, "loan")

        return self.require_exists(
            self.repository.get_by_id(loan_id),
            "Loan not found."
        )

    def _get_copy(self, copy_id):

        self.validate_id(copy_id, "copy")

        return self.require_exists(
            self.copy_repository.get_by_id(copy_id),
            "Copy not found."
        )

    def _ensure_active_loan(self, loan):

        if loan.status == "RETURNED":

            raise LoanAlreadyReturnedError(
                "Loan has already been returned."
            )

        if loan.status != "ACTIVE":

            raise BusinessRuleError(
                "Loan is not active."
            )

    def _ensure_copy_available(self, copy):

        if copy.book.is_archived:

            raise CopyUnavailableError(
                "Book is archived."
            )

        if copy.status != "AVAILABLE":

            raise CopyUnavailableError(
                "Copy is not available."
            )

        loans = self.repository.get_by_copy(
            copy.id
        )

        if any(
            loan.status == "ACTIVE"
            for loan in loans
        ):

            raise CopyUnavailableError(
                "Copy already has an active loan."
            )

    def _ensure_loan_limit(self, reader_id):

        active_loans = (
            self.repository.count_active_by_reader(
                reader_id
            )
        )

        max_loans = (
            self.setting_service.get_max_loans()
        )

        if active_loans >= max_loans:

            raise LoanLimitExceededError(
                "Reader has reached the loan limit."
            )

    def _ensure_no_own_active_reservation(
        self,
        reader_id,
        book_id
    ):

        reservations = (
            self.reservation_repository
            .get_active_by_reader(reader_id)
        )

        if any(
            reservation.book_id == book_id
            for reservation in reservations
        ):

            raise BusinessRuleError(
                "Reader has an active reservation "
                "for this book. Use reservation "
                "fulfillment instead."
            )

    def _ensure_copy_consistency(self, loan):

        if loan.copy.status != "LOANED":

            raise BusinessRuleError(
                "Copy status is inconsistent with "
                "the active loan."
            )

        active_loans = [
            item
            for item in self.repository.get_by_copy(
                loan.copy_id
            )
            if item.status == "ACTIVE"
        ]

        if (
            len(active_loans) != 1
            or active_loans[0].id != loan.id
        ):

            raise BusinessRuleError(
                "Inconsistent active loan records."
            )

    # ==========================================
    # INTERNAL LOAN CREATION
    # ==========================================

    def _create_loan(
        self,
        actor_id,
        reader_id,
        copy
    ):

        self.auth_service.require_staff(
            actor_id
        )

        self.reader_service.require_active_reader(
            reader_id
        )

        self._ensure_loan_limit(reader_id)

        if copy.book.is_archived:

            raise CopyUnavailableError(
                "Book is archived."
            )

        if copy.status not in (
            "AVAILABLE",
            "RESERVED"
        ):

            raise CopyUnavailableError(
                "Copy is not available."
            )

        if any(
            loan.status == "ACTIVE"
            for loan in self.repository.get_by_copy(
                copy.id
            )
        ):

            raise CopyUnavailableError(
                "Copy already has an active loan."
            )

        borrowed_at = self.now()

        due_date = borrowed_at + timedelta(
            days=self.setting_service.get_loan_days()
        )

        loan = Loan(
            copy_id=copy.id,
            reader_id=reader_id,
            borrowed_at=borrowed_at,
            due_date=due_date,
            status="ACTIVE"
        )

        self.repository.add(loan)

        copy.status = "LOANED"

        db.session.flush()

        self.audit_service.log(
            action="LOAN_CREATED",
            user_id=actor_id,
            description=(
                f"Loan ID: {loan.id}; "
                f"Reader ID: {reader_id}; "
                f"Copy ID: {copy.id}"
            )
        )

        return loan

    # ==========================================
    # BORROW
    # ==========================================

    def borrow_book(
        self,
        actor_id,
        reader_id,
        copy_id
    ):

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            self.validate_id(
                reader_id,
                "reader"
            )

            reader = (
                self.reader_service.require_active_reader(
                    reader_id
                )
            )

            copy = self._get_copy(copy_id)

            # Initial availability validation.
            self._ensure_copy_available(copy)

            # Validate reader loan limit.
            self._ensure_loan_limit(reader.id)

            # Process FIFO reservation queue.
            self.reservation_service._process_queue(
                copy.book_id,
                actor_id
            )

            db.session.flush()

            # Ensure that the copy is still available
            # after processing reservations.
            self._ensure_copy_available(copy)

            # Prevent bypassing the reader's own
            # active reservation.
            self._ensure_no_own_active_reservation(
                reader.id,
                copy.book_id
            )

            # Create loan using shared business logic.
            loan = self._create_loan(
                actor_id,
                reader.id,
                copy
            )

        return loan

    # ==========================================
    # OVERDUE CALCULATIONS
    # ==========================================

    def _calculate_overdue_days(
        self,
        due_date,
        reference_date
    ):

        if reference_date <= due_date:
            return 0

        difference = reference_date - due_date

        days = difference.days

        if (
            difference.seconds > 0
            or difference.microseconds > 0
        ):

            days += 1

        return days

    def _get_overdue_days(self, loan):

        if loan.status == "CANCELLED":
            return 0

        if loan.status == "RETURNED":

            if loan.returned_at is None:

                raise BusinessRuleError(
                    "Returned loan has no return date."
                )

            reference_date = loan.returned_at

        else:

            reference_date = self.now()

        return self._calculate_overdue_days(
            loan.due_date,
            reference_date
        )

    def get_overdue_days(
        self,
        actor_id,
        loan_id
    ):

        loan = self.get_by_id(
            actor_id,
            loan_id
        )

        return self._get_overdue_days(loan)

    def is_overdue(
        self,
        actor_id,
        loan_id
    ):

        loan = self.get_by_id(
            actor_id,
            loan_id
        )

        return (
            loan.status == "ACTIVE"
            and loan.due_date < self.now()
        )

    # ==========================================
    # FINE CALCULATIONS
    # ==========================================

    def _calculate_fine_amount(
        self,
        overdue_days
    ):

        return self.fine_service.calculate_fine_amount(
            overdue_days
        )

    def calculate_fine(
        self,
        actor_id,
        loan_id
    ):

        loan = self.get_by_id(
            actor_id,
            loan_id
        )

        if loan.status == "CANCELLED":

            return Decimal("0.00")

        existing_fine = (
            self.fine_repository.get_by_loan(
                loan.id
            )
        )

        if existing_fine is not None:

            return existing_fine.amount

        if loan.status == "RETURNED":

            return Decimal("0.00")

        overdue_days = self._get_overdue_days(
            loan
        )

        return self._calculate_fine_amount(
            overdue_days
        )

    def _create_return_fine(
        self,
        actor_id,
        loan,
        returned_at
    ):

        overdue_days = (
            self._calculate_overdue_days(
                loan.due_date,
                returned_at
            )
        )

        return self.fine_service._create_return_fine(
            actor_id,
            loan,
            overdue_days
        )

    # ==========================================
    # RETURN
    # ==========================================

    def return_book(
        self,
        actor_id,
        loan_id
    ):

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            loan = self._get_loan(loan_id)

            self._ensure_active_loan(loan)

            self._ensure_copy_consistency(loan)

            returned_at = self.now()

            if (
                loan.borrowed_at is not None
                and returned_at < loan.borrowed_at
            ):

                raise BusinessRuleError(
                    "Return date precedes borrowing date."
                )

            self._create_return_fine(
                actor_id,
                loan,
                returned_at
            )

            loan.returned_at = returned_at
            loan.status = "RETURNED"

            loan.copy.status = "AVAILABLE"

            db.session.flush()

            # Returned copies are offered to the
            # reservation queue.
            self.reservation_service._process_queue(
                loan.copy.book_id,
                actor_id
            )

            self.audit_service.log(
                action="LOAN_RETURNED",
                user_id=actor_id,
                description=(
                    f"Returned loan ID: {loan.id}; "
                    f"Copy ID: {loan.copy_id}"
                )
            )

        return loan

    # ==========================================
    # CANCEL
    # ==========================================

    def cancel_loan(
        self,
        actor_id,
        loan_id,
        reason
    ):

        with self.transaction():

            self.auth_service.require_admin(
                actor_id
            )

            reason = self.require_text(
                reason,
                "Cancellation reason"
            )

            if len(reason) > 1000:

                raise ValidationError(
                    "Cancellation reason is too long."
                )

            loan = self._get_loan(loan_id)

            self._ensure_active_loan(loan)

            self._ensure_copy_consistency(loan)

            if loan.due_date < self.now():

                raise BusinessRuleError(
                    "Overdue loans cannot be cancelled."
                )

            if (
                self.fine_repository.get_by_loan(
                    loan.id
                ) is not None
            ):

                raise BusinessRuleError(
                    "Cannot cancel a loan with a fine."
                )

            loan.status = "CANCELLED"
            loan.returned_at = None

            loan.copy.status = "AVAILABLE"

            db.session.flush()

            # Released copies are offered to the
            # reservation queue.
            self.reservation_service._process_queue(
                loan.copy.book_id,
                actor_id
            )

            self.audit_service.log(
                action="LOAN_CANCELLED",
                user_id=actor_id,
                description=(
                    f"Loan ID: {loan.id}; "
                    f"Reason: {reason}"
                )
            )

        return loan

    # ==========================================
    # READ
    # ==========================================

    def get_by_id(
        self,
        actor_id,
        loan_id
    ):

        user = (
            self.auth_service.get_current_user(
                actor_id
            )
        )

        self.validate_id(
            loan_id,
            "loan"
        )

        loan = self.repository.get_by_id(
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

        return loan

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

    def get_by_copy(
        self,
        actor_id,
        copy_id
    ):

        self.auth_service.require_staff(
            actor_id
        )

        copy = self._get_copy(copy_id)

        return self.repository.get_by_copy(
            copy.id
        )

    def get_active_loans(self, actor_id):

        self.auth_service.require_staff(
            actor_id
        )

        return self.repository.get_active_loans()

    def get_active_by_reader(
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

        return self.repository.get_active_by_reader(
            reader_id
        )

    def get_active_by_copy(
        self,
        actor_id,
        copy_id
    ):

        self.auth_service.require_staff(
            actor_id
        )

        copy = self._get_copy(copy_id)

        loans = [
            loan
            for loan in self.repository.get_by_copy(
                copy.id
            )
            if loan.status == "ACTIVE"
        ]

        if len(loans) > 1:

            raise BusinessRuleError(
                "Copy has multiple active loans."
            )

        return loans[0] if loans else None

    def get_overdue_loans(self, actor_id):

        self.auth_service.require_staff(
            actor_id
        )

        return self.repository.get_overdue_loans()

    def get_by_status(
        self,
        actor_id,
        status
    ):

        self.auth_service.require_staff(
            actor_id
        )

        status = self.validate_status(status)

        return [
            loan
            for loan in self.repository.get_all()
            if loan.status == status
        ]

    # ==========================================
    # READER PROFILE
    # ==========================================

    def get_own_loans(self, actor_id):

        reader = (
            self.reader_service.get_own_profile(
                actor_id
            )
        )

        return self.repository.get_by_reader(
            reader.id
        )

    def get_own_active_loans(self, actor_id):

        reader = (
            self.reader_service.get_own_profile(
                actor_id
            )
        )

        return self.repository.get_active_by_reader(
            reader.id
        )

    def count_active_by_reader(
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

        return self.repository.count_active_by_reader(
            reader_id
        )

    def get_remaining_loan_limit(
        self,
        actor_id,
        reader_id
    ):

        active_loans = (
            self.count_active_by_reader(
                actor_id,
                reader_id
            )
        )

        max_loans = (
            self.setting_service.get_max_loans()
        )

        return max(
            0,
            max_loans - active_loans
        )

    def count(self, actor_id):

        self.auth_service.require_staff(
            actor_id
        )

        return self.repository.count()
    