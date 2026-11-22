from datetime import datetime, timezone, timedelta

from app.extensions import db
from app.models import Reservation

from app.repositories import (
    ReservationRepository,
    BookRepository,
    CopyRepository,
    LoanRepository
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
    AuthorizationError,
    ReservationLimitExceededError,
    ReservationAlreadyExistsError
)


class ReservationService(BaseService):
    """Service responsible for library reservations."""

    VALID_STATUSES = (
        "WAITING",
        "READY",
        "FULFILLED",
        "CANCELLED",
        "EXPIRED"
    )

    ACTIVE_STATUSES = (
        "WAITING",
        "READY"
    )

    def __init__(self):

        self.repository = ReservationRepository()
        self.book_repository = BookRepository()
        self.copy_repository = CopyRepository()
        self.loan_repository = LoanRepository()

        self.auth_service = AuthService()
        self.audit_service = AuditService()
        self.reader_service = ReaderService()
        self.setting_service = SettingService()

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
                "Invalid reservation status."
            )

        return status

    # ==========================================
    # INTERNAL METHODS
    # ==========================================

    def _get_reservation(self, reservation_id):

        self.validate_id(
            reservation_id,
            "reservation"
        )

        return self.require_exists(
            self.repository.get_by_id(
                reservation_id
            ),
            "Reservation not found."
        )

    def _get_book(self, book_id):

        self.validate_id(
            book_id,
            "book"
        )

        return self.require_exists(
            self.book_repository.get_by_id(
                book_id
            ),
            "Book not found."
        )

    def _ensure_active_book(self, book_id):

        book = self._get_book(book_id)

        if book.is_archived:

            raise BusinessRuleError(
                "Book is archived."
            )

        return book

    def _ensure_reservation_limit(self, reader_id):

        active = (
            self.repository.count_active_by_reader(
                reader_id
            )
        )

        maximum = (
            self.setting_service.get_max_reservations()
        )

        if active >= maximum:

            raise ReservationLimitExceededError(
                "Reader has reached the reservation limit."
            )

    def _ensure_no_duplicate(
        self,
        reader_id,
        book_id
    ):

        reservations = (
            self.repository.get_active_by_reader(
                reader_id
            )
        )

        if any(
            reservation.book_id == book_id
            for reservation in reservations
        ):

            raise ReservationAlreadyExistsError(
                "Reader already has an active "
                "reservation for this book."
            )

    def _ensure_no_active_book_loan(
        self,
        reader_id,
        book_id
    ):

        loans = (
            self.loan_repository.get_active_by_reader(
                reader_id
            )
        )

        if any(
            loan.copy.book_id == book_id
            for loan in loans
        ):

            raise BusinessRuleError(
                "Reader already has an active "
                "loan for this book."
            )

    def _ensure_active_reservation(
        self,
        reservation
    ):

        if reservation.status not in self.ACTIVE_STATUSES:

            raise BusinessRuleError(
                "Reservation is not active."
            )

    def _get_reserved_copies(self, book_id):

        copies = (
            self.copy_repository.get_by_book_id(
                book_id
            )
        )

        return sorted(
            [
                copy for copy in copies
                if copy.status == "RESERVED"
            ],
            key=lambda copy: copy.id
        )

    def _get_ready_reservations(self, book_id):

        return [
            reservation
            for reservation in self.repository.get_by_book(
                book_id
            )
            if reservation.status == "READY"
        ]

    def _ensure_consistency(self, book_id):

        reserved_copies = (
            self._get_reserved_copies(book_id)
        )

        ready_reservations = (
            self._get_ready_reservations(book_id)
        )

        if len(reserved_copies) != len(ready_reservations):

            raise BusinessRuleError(
                "Reserved copies and ready reservations "
                "are inconsistent."
            )

        for copy in reserved_copies:

            active_loans = [
                loan
                for loan in self.loan_repository.get_by_copy(
                    copy.id
                )
                if loan.status == "ACTIVE"
            ]

            if active_loans:

                raise BusinessRuleError(
                    "Reserved copy has an active loan."
                )

    def _release_reserved_copy(self, book_id):

        copies = self._get_reserved_copies(
            book_id
        )

        if not copies:

            raise BusinessRuleError(
                "No reserved copy to release."
            )

        copy = copies[0]

        copy.status = "AVAILABLE"

        return copy

    # ==========================================
    # QUEUE PROCESSING
    # ==========================================

    def _expire_ready_reservations(
        self,
        book_id,
        actor_id=None
    ):

        self._ensure_consistency(book_id)

        now = self.now()
        expired = []

        reservations = (
            self._get_ready_reservations(
                book_id
            )
        )

        for reservation in reservations:

            if reservation.expires_at is None:

                raise BusinessRuleError(
                    "Ready reservation has no expiry date."
                )

            if reservation.expires_at <= now:

                copy = self._release_reserved_copy(
                    book_id
                )

                reservation.status = "EXPIRED"

                expired.append(reservation)

                self.audit_service.log(
                    action="RESERVATION_EXPIRED",
                    user_id=actor_id,
                    description=(
                        f"Reservation ID: {reservation.id}; "
                        f"Released copy ID: {copy.id}"
                    )
                )

        db.session.flush()

        return expired

    def _process_queue(
        self,
        book_id,
        actor_id=None
    ):

        book = self._get_book(book_id)

        self._ensure_consistency(book.id)

        if book.is_archived:

            return []

        self._expire_ready_reservations(
            book.id,
            actor_id
        )

        waiting = (
            self.repository.get_waiting_by_book(
                book.id
            )
        )

        available = sorted(
            self.copy_repository.get_available_copies(
                book.id
            ),
            key=lambda copy: copy.id
        )

        for copy in available:

            active_loans = [
                loan
                for loan in self.loan_repository.get_by_copy(
                    copy.id
                )
                if loan.status == "ACTIVE"
            ]

            if active_loans:

                raise BusinessRuleError(
                    "Available copy has an active loan."
                )

        reservation_days = (
            self.setting_service.get_reservation_days()
        )

        prepared = []

        for reservation in waiting:

            if not available:
                break

            reader = reservation.reader

            if (
                not reader.user.is_active
                or reader.user.role != "READER"
            ):

                reservation.status = "CANCELLED"

                self.audit_service.log(
                    action="RESERVATION_CANCELLED",
                    user_id=actor_id,
                    description=(
                        f"Reservation ID: {reservation.id}; "
                        "Inactive reader"
                    )
                )

                continue

            copy = available.pop(0)

            copy.status = "RESERVED"

            reservation.status = "READY"

            reservation.expires_at = (
                self.now()
                + timedelta(days=reservation_days)
            )

            prepared.append(reservation)

            self.audit_service.log(
                action="RESERVATION_READY",
                user_id=actor_id,
                description=(
                    f"Reservation ID: {reservation.id}; "
                    f"Book ID: {book.id}"
                )
            )

        db.session.flush()

        self._ensure_consistency(book.id)

        return prepared

    def process_queue(self, actor_id, book_id):

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            self._ensure_active_book(book_id)

            prepared = self._process_queue(
                book_id,
                actor_id
            )

        return prepared

    # ==========================================
    # CREATE RESERVATION
    # ==========================================

    def create_reservation(
        self,
        actor_id,
        reader_id,
        book_id
    ):

        with self.transaction():

            self.validate_id(
                reader_id,
                "reader"
            )

            self.auth_service.require_reader_access(
                actor_id,
                reader_id
            )

            reader = (
                self.reader_service.require_active_reader(
                    reader_id
                )
            )

            book = self._ensure_active_book(
                book_id
            )

            self._process_queue(
                book.id,
                actor_id
            )

            self._ensure_reservation_limit(
                reader.id
            )

            self._ensure_no_duplicate(
                reader.id,
                book.id
            )

            self._ensure_no_active_book_loan(
                reader.id,
                book.id
            )

            reservation = Reservation(
                reader_id=reader.id,
                book_id=book.id,
                status="WAITING",
                reserved_at=self.now(),
                expires_at=None
            )

            self.repository.add(reservation)

            db.session.flush()

            self.audit_service.log(
                action="RESERVATION_CREATED",
                user_id=actor_id,
                description=(
                    f"Reservation ID: {reservation.id}; "
                    f"Reader ID: {reader.id}; "
                    f"Book ID: {book.id}"
                )
            )

            self._process_queue(
                book.id,
                actor_id
            )

        return reservation

    def create_own_reservation(
        self,
        actor_id,
        book_id
    ):

        reader = (
            self.reader_service.get_own_profile(
                actor_id
            )
        )

        return self.create_reservation(
            actor_id,
            reader.id,
            book_id
        )

    # ==========================================
    # CANCEL RESERVATION
    # ==========================================

    def cancel_reservation(
        self,
        actor_id,
        reservation_id
    ):

        with self.transaction():

            reservation = self.get_by_id(
                actor_id,
                reservation_id
            )

            self._ensure_active_reservation(
                reservation
            )

            self._ensure_consistency(
                reservation.book_id
            )

            if reservation.status == "READY":

                if (
                    reservation.expires_at is None
                    or reservation.expires_at <= self.now()
                ):

                    raise BusinessRuleError(
                        "Reservation has expired "
                        "or has an invalid expiry date."
                    )

                self._release_reserved_copy(
                    reservation.book_id
                )

            reservation.status = "CANCELLED"

            self.audit_service.log(
                action="RESERVATION_CANCELLED",
                user_id=actor_id,
                description=(
                    f"Reservation ID: {reservation.id}"
                )
            )

            db.session.flush()

            self._process_queue(
                reservation.book_id,
                actor_id
            )

        return reservation

    # ==========================================
    # EXPIRE RESERVATIONS
    # ==========================================

    def expire_reservations(self, actor_id):

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            expired = (
                self.repository.get_expired_reservations()
            )

            book_ids = sorted({
                reservation.book_id
                for reservation in expired
            })

            results = []

            for book_id in book_ids:

                results.extend(
                    self._expire_ready_reservations(
                        book_id,
                        actor_id
                    )
                )

                self._process_queue(
                    book_id,
                    actor_id
                )

        return results

    # ==========================================
    # FULFILL RESERVATION
    # ==========================================

    def fulfill_reservation(
        self,
        actor_id,
        reservation_id,
        copy_id=None
    ):

        # Local import prevents circular imports.
        from app.services.loan_service import LoanService

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            reservation = self._get_reservation(
                reservation_id
            )

            if reservation.status != "READY":

                raise BusinessRuleError(
                    "Reservation is not ready."
                )

            if (
                reservation.expires_at is None
                or reservation.expires_at <= self.now()
            ):

                raise BusinessRuleError(
                    "Reservation has expired."
                )

            self._ensure_active_book(
                reservation.book_id
            )

            reader = (
                self.reader_service.require_active_reader(
                    reservation.reader_id
                )
            )

            self._ensure_consistency(
                reservation.book_id
            )

            self._ensure_no_active_book_loan(
                reader.id,
                reservation.book_id
            )

            copies = self._get_reserved_copies(
                reservation.book_id
            )

            if copy_id is None:

                copy = copies[0]

            else:

                self.validate_id(
                    copy_id,
                    "copy"
                )

                copy = next(
                    (
                        item for item in copies
                        if item.id == copy_id
                    ),
                    None
                )

                if copy is None:

                    raise BusinessRuleError(
                        "Invalid reserved copy."
                    )

            loan_service = LoanService()

            loan = loan_service._create_loan(
                actor_id,
                reader.id,
                copy
            )

            reservation.status = "FULFILLED"

            db.session.flush()

            self.audit_service.log(
                action="RESERVATION_FULFILLED",
                user_id=actor_id,
                description=(
                    f"Reservation ID: {reservation.id}; "
                    f"Loan ID: {loan.id}"
                )
            )

            self._process_queue(
                reservation.book_id,
                actor_id
            )

        return loan

    # ==========================================
    # READ
    # ==========================================

    def get_by_id(
        self,
        actor_id,
        reservation_id
    ):

        user = (
            self.auth_service.get_current_user(
                actor_id
            )
        )

        self.validate_id(
            reservation_id,
            "reservation"
        )

        reservation = (
            self.repository.get_by_id(
                reservation_id
            )
        )

        if reservation is None:

            if user.role == "READER":

                raise AuthorizationError(
                    "Access denied."
                )

            raise NotFoundError(
                "Reservation not found."
            )

        self.auth_service.require_reader_access(
            actor_id,
            reservation.reader_id
        )

        return reservation

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

    def get_by_book(self, actor_id, book_id):

        self.auth_service.require_staff(
            actor_id
        )

        book = self._get_book(book_id)

        return self.repository.get_by_book(
            book.id
        )

    def get_by_status(self, actor_id, status):

        self.auth_service.require_staff(
            actor_id
        )

        status = self.validate_status(status)

        return [
            reservation
            for reservation in self.repository.get_all()
            if reservation.status == status
        ]

    def get_waiting_by_book(
        self,
        actor_id,
        book_id
    ):

        self.auth_service.require_staff(
            actor_id
        )

        book = self._get_book(book_id)

        return self.repository.get_waiting_by_book(
            book.id
        )

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

    def get_own_reservations(self, actor_id):

        reader = (
            self.reader_service.get_own_profile(
                actor_id
            )
        )

        return self.repository.get_by_reader(
            reader.id
        )

    def get_own_active_reservations(self, actor_id):

        reader = (
            self.reader_service.get_own_profile(
                actor_id
            )
        )

        return self.repository.get_active_by_reader(
            reader.id
        )

    def get_expired_reservations(self, actor_id):

        self.auth_service.require_staff(
            actor_id
        )

        return self.repository.get_expired_reservations()

    # ==========================================
    # QUEUE POSITION
    # ==========================================

    def get_queue_position(
        self,
        actor_id,
        reservation_id
    ):

        reservation = self.get_by_id(
            actor_id,
            reservation_id
        )

        if reservation.status == "READY":

            if (
                reservation.expires_at is None
                or reservation.expires_at <= self.now()
            ):

                return None

            return 0

        if reservation.status != "WAITING":

            return None

        waiting = (
            self.repository.get_waiting_by_book(
                reservation.book_id
            )
        )

        for position, item in enumerate(
            waiting,
            start=1
        ):

            if item.id == reservation.id:

                return position

        return None

    # ==========================================
    # STATISTICS
    # ==========================================

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

    def get_remaining_reservation_limit(
        self,
        actor_id,
        reader_id
    ):

        active = self.count_active_by_reader(
            actor_id,
            reader_id
        )

        maximum = (
            self.setting_service.get_max_reservations()
        )

        return max(
            0,
            maximum - active
        )

    def count(self, actor_id):

        self.auth_service.require_staff(
            actor_id
        )

        return self.repository.count()