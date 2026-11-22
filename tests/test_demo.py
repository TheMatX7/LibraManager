import pytest

from app.demo import seed_demo_data
from app.exceptions import BusinessRuleError
from app.services import (
    FineService,
    PaymentService,
    ReaderService,
    UserService
)


def test_demo_seed_is_explicit_complete_and_non_destructive(app):
    credentials = seed_demo_data()
    admin = UserService().repository.get_by_username("demo_admin")
    reader = ReaderService().repository.get_by_user_id(
        UserService().repository.get_by_username("demo_reader").id
    )

    assert credentials["administrator"]["username"] == "demo_admin"
    assert len(credentials["administrator"]["password"]) >= 18
    assert UserService().repository.count() == 4
    assert reader is not None
    assert FineService().repository.count() == 1
    assert PaymentService().repository.count() == 1

    with pytest.raises(BusinessRuleError, match="empty database"):
        seed_demo_data()
