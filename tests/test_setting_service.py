from decimal import Decimal

import pytest

from app.repositories import SettingRepository
from app.services import SettingService

from app.exceptions import ValidationError


@pytest.fixture
def service(app):
    return SettingService()


def test_initialize_defaults(service):
    service.initialize_defaults()

    repository = SettingRepository()

    assert repository.count() == 5


def test_initialize_defaults_twice(service):
    service.initialize_defaults()
    service.initialize_defaults()

    repository = SettingRepository()

    assert repository.count() == 5


def test_initialize_preserves_existing_value(service):
    service.update("MAX_ACTIVE_LOANS", 10)
    service.initialize_defaults()

    assert service.get_max_loans() == 10


def test_default_max_loans(service):
    assert service.get_max_loans() == 5


def test_default_loan_days(service):
    assert service.get_loan_days() == 30


def test_default_fine_per_day(service):
    assert service.get_fine_per_day() == Decimal("1.00")


def test_default_reservation_days(service):
    assert service.get_reservation_days() == 3


def test_default_max_reservations(service):
    assert service.get_max_reservations() == 3


def test_update_max_loans(service):
    service.update("MAX_ACTIVE_LOANS", 10)

    assert service.get_max_loans() == 10


def test_update_loan_days(service):
    service.update("LOAN_PERIOD_DAYS", 60)

    assert service.get_loan_days() == 60


def test_update_fine_per_day(service):
    service.update("FINE_PER_DAY", "2.50")

    assert service.get_fine_per_day() == Decimal("2.50")


def test_zero_fine(service):
    service.update("FINE_PER_DAY", 0)

    assert service.get_fine_per_day() == Decimal("0.00")


def test_unknown_setting(service):
    with pytest.raises(ValidationError):
        service.get("UNKNOWN_SETTING")


def test_update_unknown_setting(service):
    with pytest.raises(ValidationError):
        service.update("UNKNOWN_SETTING", 10)


@pytest.mark.parametrize(
    "value",
    [0, -5, "abc", None, 2.5, True, 3651]
)
def test_invalid_max_loans(service, value):
    with pytest.raises(ValidationError):
        service.update("MAX_ACTIVE_LOANS", value)


@pytest.mark.parametrize(
    "value",
    [-1, "abc", None, "NaN", "Infinity", "1.001"]
)
def test_invalid_fine(service, value):
    with pytest.raises(ValidationError):
        service.update("FINE_PER_DAY", value)


def test_get_all_settings(service):
    settings = service.get_all()

    assert len(settings) == 5
    assert settings["MAX_ACTIVE_LOANS"] == 5
    assert settings["LOAN_PERIOD_DAYS"] == 30


def test_reset_to_defaults(service):
    service.update("MAX_ACTIVE_LOANS", 20)
    service.update("LOAN_PERIOD_DAYS", 60)
    service.update("FINE_PER_DAY", "5.00")

    service.reset_to_defaults()

    assert service.get_max_loans() == 5
    assert service.get_loan_days() == 30
    assert service.get_fine_per_day() == Decimal("1.00")


def test_setting_persistence(service):
    service.update("MAX_ACTIVE_LOANS", 15)

    new_service = SettingService()

    assert new_service.get_max_loans() == 15


def test_invalid_update_preserves_value(service):
    service.update("MAX_ACTIVE_LOANS", 10)

    with pytest.raises(ValidationError):
        service.update("MAX_ACTIVE_LOANS", -1)

    assert service.get_max_loans() == 10