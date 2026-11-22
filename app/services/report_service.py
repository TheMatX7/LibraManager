"""Read-only reporting service for LibraManager.

All timestamps stored by the current schema are naive UTC ``datetime``
instances.  Public methods accepting a reporting period therefore expect the
same representation; converting a local time at the HTTP/CLI boundary avoids
ambiguous reports around daylight-saving changes.
"""

import csv
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO

from sqlalchemy import func, select

from app.extensions import db
from app.models import (
    Book,
    Category,
    Copy,
    Fine,
    Loan,
    Payment,
    Reader,
    Reservation,
    User
)
from app.services.auth_service import AuthService
from app.services.base_service import BaseService
from app.services.fine_service import FineService
from app.services.payment_service import PaymentService
from app.services.audit_service import AuditService
from app.exceptions import ValidationError


class ReportService(BaseService):
    """Build read-only operational and financial reports for staff users."""

    COPY_STATUSES = (
        "AVAILABLE",
        "LOANED",
        "RESERVED",
        "DAMAGED",
        "LOST"
    )

    RESERVATION_STATUSES = (
        "WAITING",
        "READY",
        "FULFILLED",
        "CANCELLED",
        "EXPIRED"
    )

    ZERO = Decimal("0.00")
    MONEY_PRECISION = Decimal("0.01")

    def __init__(self):
        self.auth_service = AuthService()
        self.audit_service = AuditService()
        self.fine_service = FineService()
        self.payment_service = PaymentService()

    # ==========================================
    # INPUT VALIDATION AND READ HELPERS
    # ==========================================

    def validate_limit(self, limit):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValidationError(
                "Report limit must be an integer between 1 and 100."
            )

        return limit

    def validate_period(self, start_at=None, end_at=None):
        for value, field_name in (
            (start_at, "Report start"),
            (end_at, "Report end")
        ):
            if value is None:
                continue

            if (
                not isinstance(value, datetime)
                or value.tzinfo is not None
            ):
                raise ValidationError(
                    f"{field_name} must be a naive UTC datetime."
                )

        if (
            start_at is not None
            and end_at is not None
            and start_at > end_at
        ):
            raise ValidationError(
                "Report start must not be later than report end."
            )

        return start_at, end_at

    @staticmethod
    def _count(model):
        return db.session.scalar(
            select(func.count()).select_from(model)
        )

    @staticmethod
    def _utc_now():
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _as_money(value):
        if value is None:
            return ReportService.ZERO

        return Decimal(str(value)).quantize(
            ReportService.MONEY_PRECISION
        )

    @classmethod
    def _decimal_sum(cls, column, *conditions):
        statement = select(func.coalesce(func.sum(column), 0))

        if conditions:
            statement = statement.where(*conditions)

        return cls._as_money(db.session.scalar(statement))

    @staticmethod
    def _period_conditions(column, start_at, end_at):
        conditions = []

        if start_at is not None:
            conditions.append(column >= start_at)

        if end_at is not None:
            conditions.append(column <= end_at)

        return conditions

    # ==========================================
    # LIBRARY, CATALOGUE AND LOAN REPORTS
    # ==========================================

    def get_library_overview(self, actor_id, now=None):
        """Return the aggregate data required by the staff dashboard."""

        self.auth_service.require_staff(actor_id)

        if now is None:
            now = self._utc_now()

        self.validate_period(now, now)

        copy_counts = dict(
            db.session.execute(
                select(Copy.status, func.count())
                .group_by(Copy.status)
            ).all()
        )

        overview = {
            "users": self._count(User),
            "readers": self._count(Reader),
            "books": self._count(Book),
            "active_books": db.session.scalar(
                select(func.count())
                .select_from(Book)
                .where(Book.is_archived.is_(False))
            ),
            "archived_books": db.session.scalar(
                select(func.count())
                .select_from(Book)
                .where(Book.is_archived.is_(True))
            ),
            "copies": self._count(Copy),
            "available_copies": copy_counts.get("AVAILABLE", 0),
            "active_loans": db.session.scalar(
                select(func.count())
                .select_from(Loan)
                .where(Loan.status == "ACTIVE")
            ),
            "overdue_loans": db.session.scalar(
                select(func.count())
                .select_from(Loan)
                .where(
                    Loan.status == "ACTIVE",
                    Loan.due_date < now
                )
            ),
            "active_reservations": db.session.scalar(
                select(func.count())
                .select_from(Reservation)
                .where(Reservation.status.in_(("WAITING", "READY")))
            ),
            "copy_statuses": {
                status: copy_counts.get(status, 0)
                for status in self.COPY_STATUSES
            }
        }

        return overview

    def get_loan_statistics(
        self,
        actor_id,
        start_at=None,
        end_at=None,
        now=None
    ):
        self.auth_service.require_staff(actor_id)
        start_at, end_at = self.validate_period(start_at, end_at)

        if now is None:
            now = self._utc_now()

        self.validate_period(now, now)

        borrowed_conditions = self._period_conditions(
            Loan.borrowed_at,
            start_at,
            end_at
        )
        returned_conditions = self._period_conditions(
            Loan.returned_at,
            start_at,
            end_at
        )

        return {
            "total_loans": self._count(Loan),
            "active_loans": db.session.scalar(
                select(func.count())
                .select_from(Loan)
                .where(Loan.status == "ACTIVE")
            ),
            "overdue_loans": db.session.scalar(
                select(func.count())
                .select_from(Loan)
                .where(
                    Loan.status == "ACTIVE",
                    Loan.due_date < now
                )
            ),
            "loan_history": db.session.scalar(
                select(func.count())
                .select_from(Loan)
                .where(Loan.status == "RETURNED")
            ),
            "borrowed_in_period": db.session.scalar(
                select(func.count())
                .select_from(Loan)
                .where(*borrowed_conditions)
            ),
            "returned_in_period": db.session.scalar(
                select(func.count())
                .select_from(Loan)
                .where(
                    Loan.status == "RETURNED",
                    *returned_conditions
                )
            )
        }

    def get_reservation_statistics(self, actor_id):
        self.auth_service.require_staff(actor_id)

        counts = dict(
            db.session.execute(
                select(Reservation.status, func.count())
                .group_by(Reservation.status)
            ).all()
        )

        return {
            "total_reservations": self._count(Reservation),
            "active_reservations": (
                counts.get("WAITING", 0)
                + counts.get("READY", 0)
            ),
            "statuses": {
                status: counts.get(status, 0)
                for status in self.RESERVATION_STATUSES
            }
        }

    def get_most_borrowed_books(
        self,
        actor_id,
        limit=10,
        start_at=None,
        end_at=None
    ):
        self.auth_service.require_staff(actor_id)
        limit = self.validate_limit(limit)
        start_at, end_at = self.validate_period(start_at, end_at)

        conditions = self._period_conditions(
            Loan.borrowed_at,
            start_at,
            end_at
        )

        statement = (
            select(
                Book.id,
                Book.title,
                func.count(Loan.id).label("loan_count")
            )
            .join(Copy, Copy.book_id == Book.id)
            .join(Loan, Loan.copy_id == Copy.id)
            .where(*conditions)
            .group_by(Book.id, Book.title)
            .order_by(
                func.count(Loan.id).desc(),
                Book.title.asc(),
                Book.id.asc()
            )
            .limit(limit)
        )

        return [
            {
                "book_id": row.id,
                "title": row.title,
                "loan_count": row.loan_count
            }
            for row in db.session.execute(statement)
        ]

    def get_category_statistics(self, actor_id):
        self.auth_service.require_staff(actor_id)

        statement = (
            select(
                Category.id,
                Category.name,
                func.count(func.distinct(Book.id)).label("book_count"),
                func.count(func.distinct(Copy.id)).label("copy_count"),
                func.count(Loan.id).label("loan_count")
            )
            .outerjoin(Book, Book.category_id == Category.id)
            .outerjoin(Copy, Copy.book_id == Book.id)
            .outerjoin(Loan, Loan.copy_id == Copy.id)
            .group_by(Category.id, Category.name)
            .order_by(Category.name.asc(), Category.id.asc())
        )

        return [
            {
                "category_id": row.id,
                "name": row.name,
                "book_count": row.book_count,
                "copy_count": row.copy_count,
                "loan_count": row.loan_count
            }
            for row in db.session.execute(statement)
        ]

    # ==========================================
    # FINANCIAL REPORTS
    # ==========================================

    def get_financial_statistics(self, actor_id):
        """Return verified all-time fine and payment statistics for staff."""

        self.auth_service.require_staff(actor_id)

        # The services additionally verify the financial state against the
        # append-only payment history before reporting the aggregate values.
        fine_summary = self.fine_service.get_summary(actor_id)
        payment_summary = self.payment_service.get_summary(actor_id)

        return {
            "fines": fine_summary,
            "payments": payment_summary,
            "outstanding_amount": fine_summary["total_unpaid"],
            "registered_payment_amount": payment_summary["total_amount"]
        }

    def get_financial_report(
        self,
        actor_id,
        start_at=None,
        end_at=None
    ):
        """Return payment totals for an inclusive UTC reporting period."""

        self.auth_service.require_staff(actor_id)
        start_at, end_at = self.validate_period(start_at, end_at)

        conditions = self._period_conditions(
            Payment.paid_at,
            start_at,
            end_at
        )
        method_rows = db.session.execute(
            select(
                Payment.method,
                func.coalesce(func.sum(Payment.amount), 0)
            )
            .where(*conditions)
            .group_by(Payment.method)
        ).all()
        method_totals = dict(method_rows)

        return {
            "start_at": start_at,
            "end_at": end_at,
            "payments": db.session.scalar(
                select(func.count())
                .select_from(Payment)
                .where(*conditions)
            ),
            "total_amount": self._decimal_sum(
                Payment.amount,
                *conditions
            ),
            "cash_total": self._as_money(
                method_totals.get("CASH")
            ),
            "card_total": self._as_money(
                method_totals.get("CARD")
            )
        }

    # ==========================================
    # ADMIN DASHBOARD AND CSV EXPORT
    # ==========================================

    def get_admin_dashboard(self, actor_id, now=None):
        """Return dashboard data reserved for an administrator."""

        self.auth_service.require_admin(actor_id)

        return {
            "library": self.get_library_overview(actor_id, now=now),
            "financial": self.get_financial_statistics(actor_id),
            "recent_audit": [
                {
                    "id": audit.id,
                    "action": audit.action,
                    "user_id": audit.user_id,
                    "description": audit.description,
                    "created_at": audit.created_at
                }
                for audit in self.audit_service.get_recent()
            ]
        }

    @staticmethod
    def _csv_value(value):
        if value is None:
            return ""

        if isinstance(value, datetime):
            return value.isoformat(sep=" ")

        value = str(value)

        # Protect spreadsheet users from formula injection in free-text values.
        if value[:1] in ("=", "+", "-", "@"):
            return f"'{value}"

        return value

    @classmethod
    def _flatten_row(cls, data, prefix=""):
        row = {}

        for key, value in data.items():
            column = f"{prefix}.{key}" if prefix else key

            if isinstance(value, dict):
                row.update(cls._flatten_row(value, column))
            else:
                row[column] = cls._csv_value(value)

        return row

    def export_csv(self, actor_id, report_name, **kwargs):
        """Export a whitelisted staff report as UTF-8 CSV text.

        The caller chooses only a logical report name, never SQL or an ORM
        expression.  This keeps an HTTP/CLI export endpoint read-only and
        avoids arbitrary-query exposure.
        """

        self.auth_service.require_staff(actor_id)

        report_name = self.require_text(report_name, "Report name").lower()

        reports = {
            "library_overview": self.get_library_overview,
            "loan_statistics": self.get_loan_statistics,
            "reservation_statistics": self.get_reservation_statistics,
            "financial_statistics": self.get_financial_statistics,
            "financial_report": self.get_financial_report,
            "most_borrowed_books": self.get_most_borrowed_books,
            "category_statistics": self.get_category_statistics
        }

        report_factory = reports.get(report_name)

        if report_factory is None:
            raise ValidationError("Unsupported report export.")

        data = report_factory(actor_id, **kwargs)

        if isinstance(data, list):
            rows = [self._flatten_row(item) for item in data]
        else:
            rows = [self._flatten_row(data)]

        columns = sorted({
            column
            for row in rows
            for column in row
        })
        stream = StringIO(newline="")
        writer = csv.DictWriter(
            stream,
            fieldnames=columns,
            lineterminator="\n",
            extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)

        return stream.getvalue()
