import pytest

from app.extensions import db
from app.models.models import Category
from app.services.base_service import BaseService
from app.exceptions.exceptions import (
    NotFoundError,
    ValidationError,
    DatabaseError
)


def test_require_exists():
    instance = object()

    assert BaseService.require_exists(instance) is instance


def test_require_exists_not_found():
    with pytest.raises(NotFoundError):
        BaseService.require_exists(None)


def test_require_text():
    result = BaseService.require_text(
        "  LibraManager  ",
        "Name"
    )

    assert result == "LibraManager"


@pytest.mark.parametrize("value", ["", "   ", None, 123])
def test_require_text_invalid(value):
    with pytest.raises(ValidationError):
        BaseService.require_text(value, "Name")


def test_commit(app):
    category = Category(name="Science")

    db.session.add(category)

    BaseService.commit()

    assert category.id is not None


def test_rollback(app):
    category = Category(name="History")

    db.session.add(category)

    BaseService.rollback()

    assert Category.query.count() == 0


def test_transaction_success(app):
    with BaseService.transaction():
        db.session.add(
            Category(name="Technology")
        )

    assert Category.query.count() == 1


def test_transaction_rollback(app):
    with pytest.raises(ValidationError):
        with BaseService.transaction():
            db.session.add(
                Category(name="Programming")
            )

            db.session.flush()

            raise ValidationError("Test error")

    assert Category.query.count() == 0


def test_transaction_database_error(app):
    db.session.add(Category(name="Science"))
    BaseService.commit()

    with pytest.raises(DatabaseError):
        with BaseService.transaction():
            db.session.add(Category(name="Science"))

    assert Category.query.count() == 1