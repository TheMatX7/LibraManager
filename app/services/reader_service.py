import re

from app.extensions import db
from app.models import Reader
from app.repositories import ReaderRepository

from app.services.base_service import BaseService
from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.services.audit_service import AuditService

from app.exceptions import (
    ValidationError,
    BusinessRuleError
)


class ReaderService(BaseService):
    """Service responsible for library readers."""

    def __init__(self):
        self.repository = ReaderRepository()
        self.auth_service = AuthService()
        self.user_service = UserService()
        self.audit_service = AuditService()

    def validate_name(self, value, field_name):

        value = self.require_text(
            value, field_name
        )

        if len(value) > 80:
            raise ValidationError(
                f"{field_name} cannot exceed 80 characters."
            )

        if not all(
            char.isalpha() or char in " -'’"
            for char in value
        ):
            raise ValidationError(
                f"Invalid {field_name.lower()}."
            )

        if not any(char.isalpha() for char in value):
            raise ValidationError(
                f"Invalid {field_name.lower()}."
            )

        return value

    def validate_phone(self, phone):

        if phone is None:
            return None

        if not isinstance(phone, str):
            raise ValidationError(
                "Phone must be a string."
            )

        phone = phone.strip()

        if not phone:
            return None

        if len(phone) > 30:
            raise ValidationError(
                "Phone cannot exceed 30 characters."
            )

        if not re.fullmatch(
            r"\+?[0-9 ()-]+", phone
        ):
            raise ValidationError(
                "Invalid phone number."
            )

        digits = re.sub(r"[^0-9]", "", phone)

        if len(digits) < 7 or len(digits) > 15:
            raise ValidationError(
                "Invalid phone number length."
            )

        return phone

    def generate_card_number(self, user_id):

        if type(user_id) is not int or user_id < 1:
            raise ValidationError(
                "Invalid user identifier."
            )

        return f"LIB-{user_id:06d}"

    def _get_reader(self, reader_id):

        return self.require_exists(
            self.repository.get_by_id(reader_id),
            "Reader not found."
        )

    def register_reader(
        self,
        actor_id,
        username,
        email,
        password,
        first_name,
        last_name,
        phone=None
    ):

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            first_name = self.validate_name(
                first_name, "First name"
            )

            last_name = self.validate_name(
                last_name, "Last name"
            )

            phone = self.validate_phone(phone)

            user = self.user_service._create_account(
                actor_id=actor_id,
                username=username,
                email=email,
                password=password,
                role="READER"
            )

            card_number = self.generate_card_number(
                user.id
            )

            reader = Reader(
                user_id=user.id,
                card_number=card_number,
                first_name=first_name,
                last_name=last_name,
                phone=phone
            )

            self.repository.add(reader)

            db.session.flush()

            self.audit_service.log(
                action="READER_CREATED",
                user_id=actor_id,
                description=(
                    f"Created reader ID: {reader.id}; "
                    f"Card: {reader.card_number}"
                )
            )

        return reader

    def get_by_id(self, actor_id, reader_id):

        return self.auth_service.require_reader_access(
            actor_id,
            reader_id
        )

    def get_all(self, actor_id):

        self.auth_service.require_staff(actor_id)

        return self.repository.get_all()

    def get_by_card_number(
        self,
        actor_id,
        card_number
    ):

        self.auth_service.require_staff(actor_id)

        card_number = self.require_text(
            card_number, "Card number"
        ).upper()

        return self.require_exists(
            self.repository.get_by_card_number(
                card_number
            ),
            "Reader not found."
        )

    def get_own_profile(self, actor_id):

        user = self.auth_service.require_reader(
            actor_id
        )

        return self.require_exists(
            self.repository.get_by_user_id(user.id),
            "Reader profile not found."
        )

    def search(self, actor_id, query):

        self.auth_service.require_staff(actor_id)

        query = self.require_text(
            query, "Search query"
        )

        if len(query) > 100:
            raise ValidationError(
                "Search query is too long."
            )

        return self.repository.search(query)

    def update_reader(
        self,
        actor_id,
        reader_id,
        first_name,
        last_name,
        phone=None
    ):

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            reader = self._get_reader(reader_id)

            first_name = self.validate_name(
                first_name, "First name"
            )

            last_name = self.validate_name(
                last_name, "Last name"
            )

            phone = self.validate_phone(phone)

            reader.first_name = first_name
            reader.last_name = last_name
            reader.phone = phone

            self.audit_service.log(
                action="READER_UPDATED",
                user_id=actor_id,
                description=(
                    f"Updated reader ID: {reader.id}"
                )
            )

        return reader

    def update_own_phone(self, actor_id, phone):

        with self.transaction():

            reader = self.get_own_profile(
                actor_id
            )

            reader.phone = self.validate_phone(
                phone
            )

            self.audit_service.log(
                action="READER_PHONE_UPDATED",
                user_id=actor_id,
                description="Reader updated own phone"
            )

        return reader

    def require_active_reader(self, reader_id):

        reader = self._get_reader(reader_id)

        if (
            not reader.user.is_active
            or reader.user.role != "READER"
        ):
            raise BusinessRuleError(
                "Reader account is inactive or invalid."
            )

        return reader

    def count(self, actor_id):

        self.auth_service.require_staff(actor_id)

        return self.repository.count()