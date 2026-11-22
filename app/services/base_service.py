from contextlib import contextmanager

from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.exceptions.exceptions import (
    DatabaseError,
    NotFoundError,
    ValidationError
)


class BaseService:
    """Base class for LibraManager services."""

    @staticmethod
    def commit():
        try:
            db.session.commit()
        except SQLAlchemyError as error:
            db.session.rollback()
            raise DatabaseError(
                "Database transaction failed."
            ) from error

    @staticmethod
    def rollback():
        db.session.rollback()

    @staticmethod
    @contextmanager
    def transaction():
        try:
            yield
            db.session.commit()

        except SQLAlchemyError as error:
            db.session.rollback()
            raise DatabaseError(
                "Database transaction failed."
            ) from error

        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def require_exists(instance, message="Object not found."):
        if instance is None:
            raise NotFoundError(message)

        return instance

    @staticmethod
    def require_text(value, field_name):
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(
                f"{field_name} is required."
            )

        return value.strip()