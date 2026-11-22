import re

from app.extensions import db
from app.models import Copy

from app.repositories import (
    CopyRepository,
    BookRepository,
    LoanRepository,
    ReservationRepository
)

from app.services.base_service import BaseService
from app.services.auth_service import AuthService
from app.services.audit_service import AuditService
from app.services.reservation_service import ReservationService

from app.exceptions import (
    ValidationError,
    DuplicateError,
    BusinessRuleError,
    NotFoundError
)


class CopyService(BaseService):
    """Service responsible for physical book copies."""

    VALID_STATUSES = (
        "AVAILABLE",
        "LOANED",
        "RESERVED",
        "DAMAGED",
        "LOST"
    )

    MANUAL_STATUSES = (
        "AVAILABLE",
        "DAMAGED",
        "LOST"
    )

    def __init__(self):

        self.repository = CopyRepository()
        self.book_repository = BookRepository()
        self.loan_repository = LoanRepository()
        self.reservation_repository = ReservationRepository()

        self.auth_service = AuthService()
        self.audit_service = AuditService()
        self.reservation_service = ReservationService()

    # ==========================================
    # VALIDATION
    # ==========================================

    def validate_id(self, value, field_name):

        if type(value) is not int or value < 1:

            raise ValidationError(
                f"Invalid {field_name} identifier."
            )

        return value

    def validate_inventory_number(
        self,
        inventory_number
    ):

        inventory_number = self.require_text(
            inventory_number,
            "Inventory number"
        )

        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_/-]{0,49}",
            inventory_number
        ):

            raise ValidationError(
                "Invalid inventory number."
            )

        return inventory_number.upper()

    def validate_status(self, status):

        if not isinstance(status, str):

            raise ValidationError(
                "Status must be a string."
            )

        status = status.strip().upper()

        if status not in self.VALID_STATUSES:

            raise ValidationError(
                "Invalid copy status."
            )

        return status

    # ==========================================
    # INTERNAL METHODS
    # ==========================================

    def _get_copy(self, copy_id):

        self.validate_id(copy_id, "copy")

        return self.require_exists(
            self.repository.get_by_id(copy_id),
            "Copy not found."
        )

    def _get_book(self, book_id):

        self.validate_id(book_id, "book")

        return self.require_exists(
            self.book_repository.get_by_id(book_id),
            "Book not found."
        )

    def _require_active_book(self, book_id):

        book = self._get_book(book_id)

        if book.is_archived:

            raise BusinessRuleError(
                "Cannot modify copies of archived books."
            )

        return book

    def _find_inventory_number(
        self,
        inventory_number
    ):

        matches = [
            copy
            for copy in self.repository.get_all()
            if copy.inventory_number.strip().upper()
            == inventory_number
        ]

        if len(matches) > 1:

            raise BusinessRuleError(
                "Multiple matching inventory numbers."
            )

        return matches[0] if matches else None

    def _check_duplicate_inventory_number(
        self,
        inventory_number,
        exclude_id=None
    ):

        existing = self._find_inventory_number(
            inventory_number
        )

        if (
            existing is not None
            and existing.id != exclude_id
        ):

            raise DuplicateError(
                "Inventory number already exists."
            )

    def _ensure_no_active_loan(self, copy_id):

        loans = self.loan_repository.get_by_copy(
            copy_id
        )

        if any(
            loan.status == "ACTIVE"
            for loan in loans
        ):

            raise BusinessRuleError(
                "Copy has an active loan."
            )

    def _ensure_no_active_reservations(
        self,
        book_id
    ):

        reservations = (
            self.reservation_repository.get_by_book(
                book_id
            )
        )

        if any(
            reservation.status in ("WAITING", "READY")
            for reservation in reservations
        ):

            raise BusinessRuleError(
                "Book has active reservations."
            )

    def _ensure_unmanaged_copy(self, copy):

        if copy.status in ("LOANED", "RESERVED"):

            raise BusinessRuleError(
                "Copy is controlled by a loan "
                "or reservation."
            )

        self._ensure_no_active_loan(copy.id)

    def _require_inventory_access(
        self,
        actor_id,
        include_archived
    ):

        self.auth_service.require_staff(actor_id)

        if type(include_archived) is not bool:

            raise ValidationError(
                "Include archived must be a boolean."
            )

    # ==========================================
    # CREATE
    # ==========================================

    def create_copy(
        self,
        actor_id,
        book_id,
        inventory_number
    ):

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            book = self._require_active_book(
                book_id
            )

            inventory_number = (
                self.validate_inventory_number(
                    inventory_number
                )
            )

            self._check_duplicate_inventory_number(
                inventory_number
            )

            copy = Copy(
                book_id=book.id,
                inventory_number=inventory_number,
                status="AVAILABLE"
            )

            self.repository.add(copy)

            db.session.flush()

            self.audit_service.log(
                action="COPY_CREATED",
                user_id=actor_id,
                description=(
                    f"Created copy ID: {copy.id}; "
                    f"Book ID: {book.id}; "
                    f"Inventory: {inventory_number}"
                )
            )

            # Offer available copies to the
            # reservation queue.
            self.reservation_service._process_queue(
                book.id,
                actor_id
            )

        return copy

    # ==========================================
    # READ
    # ==========================================

    def get_by_id(
        self,
        actor_id,
        copy_id,
        include_archived=False
    ):

        self._require_inventory_access(
            actor_id,
            include_archived
        )

        copy = self._get_copy(copy_id)

        if copy.book.is_archived and not include_archived:

            raise NotFoundError(
                "Copy not found."
            )

        return copy

    def get_by_inventory_number(
        self,
        actor_id,
        inventory_number,
        include_archived=False
    ):

        self._require_inventory_access(
            actor_id,
            include_archived
        )

        inventory_number = (
            self.validate_inventory_number(
                inventory_number
            )
        )

        copy = self.require_exists(
            self._find_inventory_number(
                inventory_number
            ),
            "Copy not found."
        )

        if copy.book.is_archived and not include_archived:

            raise NotFoundError(
                "Copy not found."
            )

        return copy

    def get_all(
        self,
        actor_id,
        include_archived=False
    ):

        self._require_inventory_access(
            actor_id,
            include_archived
        )

        copies = self.repository.get_all()

        if include_archived:

            return copies

        return [
            copy for copy in copies
            if not copy.book.is_archived
        ]

    def get_by_book_id(
        self,
        actor_id,
        book_id,
        include_archived=False
    ):

        self._require_inventory_access(
            actor_id,
            include_archived
        )

        book = self._get_book(book_id)

        if book.is_archived and not include_archived:

            raise NotFoundError(
                "Book not found."
            )

        return self.repository.get_by_book_id(
            book.id
        )

    def get_by_status(
        self,
        actor_id,
        status,
        include_archived=False
    ):

        self._require_inventory_access(
            actor_id,
            include_archived
        )

        status = self.validate_status(status)

        copies = self.repository.get_by_status(
            status
        )

        if include_archived:

            return copies

        return [
            copy for copy in copies
            if not copy.book.is_archived
        ]

    def search(
        self,
        actor_id,
        query,
        include_archived=False
    ):

        copies = self.get_all(
            actor_id,
            include_archived
        )

        query = self.require_text(
            query,
            "Search query"
        ).upper()

        if len(query) > 50:

            raise ValidationError(
                "Search query is too long."
            )

        return sorted(
            [
                copy for copy in copies
                if query in copy.inventory_number.upper()
            ],
            key=lambda copy: (
                copy.inventory_number.upper(),
                copy.id
            )
        )

    # ==========================================
    # UPDATE
    # ==========================================

    def update_copy(
        self,
        actor_id,
        copy_id,
        inventory_number
    ):

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            copy = self._get_copy(copy_id)

            self._require_active_book(
                copy.book_id
            )

            self._ensure_unmanaged_copy(copy)

            inventory_number = (
                self.validate_inventory_number(
                    inventory_number
                )
            )

            self._check_duplicate_inventory_number(
                inventory_number,
                exclude_id=copy.id
            )

            old_number = copy.inventory_number

            if old_number == inventory_number:

                return copy

            copy.inventory_number = inventory_number

            self.audit_service.log(
                action="COPY_UPDATED",
                user_id=actor_id,
                description=(
                    f"Copy ID: {copy.id}; "
                    f"{old_number} -> {inventory_number}"
                )
            )

        return copy

    # ==========================================
    # STATUS MANAGEMENT
    # ==========================================

    def change_status(
        self,
        actor_id,
        copy_id,
        new_status
    ):

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            copy = self._get_copy(copy_id)

            self._require_active_book(
                copy.book_id
            )

            new_status = self.validate_status(
                new_status
            )

            if new_status not in self.MANUAL_STATUSES:

                raise BusinessRuleError(
                    "Status must be managed by the "
                    "loan or reservation service."
                )

            self._ensure_unmanaged_copy(copy)

            old_status = copy.status

            if old_status == new_status:

                return copy

            copy.status = new_status

            db.session.flush()

            self.audit_service.log(
                action="COPY_STATUS_CHANGED",
                user_id=actor_id,
                description=(
                    f"Copy ID: {copy.id}; "
                    f"{old_status} -> {new_status}"
                )
            )

            # Synchronize reservations whenever
            # copy availability changes.
            if (
                old_status == "AVAILABLE"
                or new_status == "AVAILABLE"
            ):

                self.reservation_service._process_queue(
                    copy.book_id,
                    actor_id
                )

        return copy

    def mark_damaged(self, actor_id, copy_id):

        return self.change_status(
            actor_id,
            copy_id,
            "DAMAGED"
        )

    def mark_lost(self, actor_id, copy_id):

        return self.change_status(
            actor_id,
            copy_id,
            "LOST"
        )

    def restore_availability(
        self,
        actor_id,
        copy_id
    ):

        return self.change_status(
            actor_id,
            copy_id,
            "AVAILABLE"
        )

    # ==========================================
    # DELETE
    # ==========================================

    def delete_copy(self, actor_id, copy_id):

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            copy = self._get_copy(copy_id)

            self._require_active_book(
                copy.book_id
            )

            self._ensure_unmanaged_copy(copy)

            loans = self.loan_repository.get_by_copy(
                copy.id
            )

            if loans:

                raise BusinessRuleError(
                    "Cannot delete a copy with loan history."
                )

            # Preserve active reservation protection.
            self._ensure_no_active_reservations(
                copy.book_id
            )

            self.repository.delete(copy)

            self.audit_service.log(
                action="COPY_DELETED",
                user_id=actor_id,
                description=(
                    f"Deleted copy ID: {copy_id}"
                )
            )

        return True

    # ==========================================
    # AVAILABILITY
    # ==========================================

    def get_available_copies(
        self,
        actor_id,
        book_id
    ):

        self.auth_service.require_staff(actor_id)

        book = self._get_book(book_id)

        if book.is_archived:

            raise NotFoundError(
                "Book not found."
            )

        return self.repository.get_available_copies(
            book.id
        )

    def count_available_copies(
        self,
        actor_id,
        book_id
    ):

        self.auth_service.get_current_user(
            actor_id
        )

        book = self._get_book(book_id)

        if book.is_archived:

            raise NotFoundError(
                "Book not found."
            )

        return self.repository.count_available_copies(
            book.id
        )

    def is_available(self, actor_id, book_id):

        return self.count_available_copies(
            actor_id,
            book_id
        ) > 0

    def count(
        self,
        actor_id,
        include_archived=False
    ):

        return len(
            self.get_all(
                actor_id,
                include_archived
            )
        )