from sqlalchemy import select, func
from decimal import Decimal

from app.extensions import db
from app.models import Fine, Loan
from app.repositories.base_repository import BaseRepository


class FineRepository(BaseRepository):
    """Repository responsible for financial fine records."""

    def __init__(self):

        super().__init__(Fine)

    # ==========================================
    # FINE BY LOAN
    # ==========================================

    def get_by_loan(self, loan_id):

        statement = select(Fine).where(
            Fine.loan_id == loan_id
        )

        return db.session.scalar(statement)

    # ==========================================
    # FINES BY READER
    # ==========================================

    def get_by_reader(self, reader_id):

        statement = select(Fine).join(Loan).where(
            Loan.reader_id == reader_id
        )

        return db.session.scalars(statement).all()

    # ==========================================
    # UNPAID FINES
    # ==========================================

    def get_unpaid_fines(self):

        statement = select(Fine).where(
            Fine.status.in_(
                ["UNPAID", "PARTIALLY_PAID"]
            )
        )

        return db.session.scalars(statement).all()

    # ==========================================
    # TOTAL UNPAID AMOUNT BY READER
    # ==========================================

    def get_total_unpaid_by_reader(self, reader_id):

        statement = select(
            func.sum(
                Fine.amount - Fine.paid_amount
            )
        ).join(Loan).where(
            Loan.reader_id == reader_id,
            Fine.status.in_(
                ["UNPAID", "PARTIALLY_PAID"]
            )
        )

        result = db.session.scalar(statement)

        return (
            result
            if result is not None
            else Decimal("0.00")
        )

    # ==========================================
    # ATOMIC PAYMENT STATE UPDATE
    # ==========================================

    def update_payment_state(
        self,
        fine_id,
        expected_amount,
        expected_paid_amount,
        expected_status,
        new_paid_amount,
        new_status
    ):

        """
        Update a fine only if its previous financial state
        still matches the expected values.

        Returns True when exactly one record is updated.

        This method does not commit or roll back.

        The caller must validate business rules, manage
        the transaction and refresh the ORM instance.

        The caller must not have pending modifications
        to the same fine.
        """

        table = Fine.__table__

        statement = (
            table.update()
            .where(
                table.c.id == fine_id,
                table.c.amount == expected_amount,
                table.c.paid_amount == (
                    expected_paid_amount
                ),
                table.c.status == expected_status
            )
            .values(
                paid_amount=new_paid_amount,
                status=new_status
            )
        )

        result = db.session.execute(statement)

        return result.rowcount == 1