from decimal import Decimal, InvalidOperation

from app.repositories import SettingRepository
from app.services.base_service import BaseService
from app.exceptions import ValidationError


class SettingService(BaseService):
    """Service responsible for library configuration."""

    DEFAULT_SETTINGS = {
        "MAX_ACTIVE_LOANS": (
            5,
            "Maximum number of active loans"
        ),
        "LOAN_PERIOD_DAYS": (
            30,
            "Loan period in days"
        ),
        "FINE_PER_DAY": (
            Decimal("1.00"),
            "Daily overdue fine in PLN"
        ),
        "RESERVATION_PERIOD_DAYS": (
            3,
            "Reservation collection period in days"
        ),
        "MAX_ACTIVE_RESERVATIONS": (
            3,
            "Maximum number of active reservations"
        )
    }

    def __init__(self):
        self.repository = SettingRepository()

    def initialize_defaults(self):
        with self.transaction():
            for key, (value, description) in self.DEFAULT_SETTINGS.items():
                if self.repository.get_by_key(key) is None:
                    self.repository.set_value(
                        key,
                        value,
                        description
                    )

    def validate_key(self, key):
        if not isinstance(key, str) or key not in self.DEFAULT_SETTINGS:
            raise ValidationError(
                f"Unknown setting: {key}"
            )

    def validate_value(self, key, value):
        self.validate_key(key)

        if key == "FINE_PER_DAY":
            try:
                amount = Decimal(str(value))

                if not amount.is_finite():
                    raise ValueError()

                if amount < 0 or amount > Decimal("99999999.99"):
                    raise ValueError()

                if amount != amount.quantize(Decimal("0.01")):
                    raise ValueError()

                return amount.quantize(Decimal("0.01"))

            except (InvalidOperation, ValueError, TypeError):
                raise ValidationError(
                    "Fine must be a valid non-negative monetary amount."
                )

        try:
            if isinstance(value, bool):
                raise ValueError()

            number = int(str(value))

        except (ValueError, TypeError):
            raise ValidationError(
                f"{key} must be an integer."
            )

        if number < 1 or number > 3650:
            raise ValidationError(
                f"{key} must be between 1 and 3650."
            )

        return number

    def get(self, key):
        self.validate_key(key)

        default_value = self.DEFAULT_SETTINGS[key][0]

        value = self.repository.get_value(
            key,
            default_value
        )

        return self.validate_value(key, value)

    def update(self, key, value):
        value = self.validate_value(key, value)

        description = self.DEFAULT_SETTINGS[key][1]

        with self.transaction():
            self.repository.set_value(
                key,
                value,
                description
            )

        return value

    def get_all(self):
        return {
            key: self.get(key)
            for key in self.DEFAULT_SETTINGS
        }

    def reset_to_defaults(self):
        with self.transaction():
            for key, (value, description) in self.DEFAULT_SETTINGS.items():
                self.repository.set_value(
                    key,
                    value,
                    description
                )

    def get_max_loans(self):
        return self.get("MAX_ACTIVE_LOANS")

    def get_loan_days(self):
        return self.get("LOAN_PERIOD_DAYS")

    def get_fine_per_day(self):
        return self.get("FINE_PER_DAY")

    def get_reservation_days(self):
        return self.get("RESERVATION_PERIOD_DAYS")

    def get_max_reservations(self):
        return self.get("MAX_ACTIVE_RESERVATIONS")