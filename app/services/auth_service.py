from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from app.repositories import (
    UserRepository,
    ReaderRepository
)

from app.services.base_service import BaseService
from app.services.audit_service import AuditService

from app.exceptions import (
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    InactiveAccountError
)


class AuthService(BaseService):
    """Authentication and authorization service."""

    VALID_ROLES = (
        "ADMIN",
        "LIBRARIAN",
        "READER"
    )

    MIN_PASSWORD_LENGTH = 12
    MAX_PASSWORD_LENGTH = 128

    DUMMY_HASH = generate_password_hash(
        "DummyPasswordForVerification!",
        method="scrypt"
    )

    def __init__(self):
        self.user_repository = UserRepository()
        self.reader_repository = ReaderRepository()
        self.audit_service = AuditService()

    def validate_password(self, password):

        if not isinstance(password, str):
            raise ValidationError(
                "Password must be a string."
            )

        if len(password) < self.MIN_PASSWORD_LENGTH:
            raise ValidationError(
                "Password must contain at least 12 characters."
            )

        if len(password) > self.MAX_PASSWORD_LENGTH:
            raise ValidationError(
                "Password cannot exceed 128 characters."
            )

        if not password.strip():
            raise ValidationError(
                "Password cannot be empty."
            )

        return password

    def hash_password(self, password):

        self.validate_password(password)

        return generate_password_hash(
            password,
            method="scrypt"
        )

    def verify_password(self, password_hash, password):

        if not isinstance(password_hash, str):
            return False

        if not isinstance(password, str):
            return False

        if not password or len(password) > self.MAX_PASSWORD_LENGTH:
            return False

        try:
            return check_password_hash(
                password_hash,
                password
            )

        except (ValueError, TypeError):
            return False

    def authenticate(self, username, password):

        if (
            not isinstance(username, str)
            or not username.strip()
            or len(username.strip()) > 80
            or not isinstance(password, str)
            or not password
            or len(password) > self.MAX_PASSWORD_LENGTH
        ):
            self.audit_service.record(
                action="LOGIN_FAILED",
                description="Invalid authentication input"
            )

            raise AuthenticationError(
                "Invalid username or password."
            )

        username = username.strip()

        user = self.user_repository.get_by_username(
            username
        )

        password_hash = (
            user.password_hash
            if user is not None
            else self.DUMMY_HASH
        )

        password_valid = self.verify_password(
            password_hash,
            password
        )

        if user is None or not password_valid:

            self.audit_service.record(
                action="LOGIN_FAILED",
                user_id=user.id if user else None,
                description="Invalid authentication credentials"
            )

            raise AuthenticationError(
                "Invalid username or password."
            )

        if not user.is_active:

            self.audit_service.record(
                action="LOGIN_FAILED",
                user_id=user.id,
                description="Inactive account"
            )

            raise InactiveAccountError(
                "User account is inactive."
            )

        self.audit_service.record(
            action="LOGIN_SUCCESS",
            user_id=user.id,
            description="User logged in successfully"
        )

        return user

    def get_current_user(self, user_id):

        if type(user_id) is not int or user_id < 1:
            raise AuthenticationError(
                "Authentication required."
            )

        user = self.user_repository.get_by_id(
            user_id
        )

        if user is None:
            raise AuthenticationError(
                "Authentication required."
            )

        if not user.is_active:
            raise InactiveAccountError(
                "User account is inactive."
            )

        return user

    def require_role(self, user_id, *allowed_roles):

        user = self.get_current_user(user_id)

        if not allowed_roles:
            raise AuthorizationError(
                "No permitted roles configured."
            )

        if user.role not in allowed_roles:
            raise AuthorizationError(
                "Insufficient permissions."
            )

        return user

    def require_admin(self, user_id):

        return self.require_role(
            user_id,
            "ADMIN"
        )

    def require_staff(self, user_id):

        return self.require_role(
            user_id,
            "ADMIN",
            "LIBRARIAN"
        )

    def require_reader(self, user_id):

        return self.require_role(
            user_id,
            "READER"
        )

    def require_reader_access(self, user_id, reader_id):

        user = self.get_current_user(user_id)

        reader = self.reader_repository.get_by_id(
            reader_id
        )

        if reader is None:
            raise AuthorizationError(
                "Access denied."
            )

        if user.role in ("ADMIN", "LIBRARIAN"):
            return reader

        if (
            user.role == "READER"
            and reader.user_id == user.id
        ):
            return reader

        raise AuthorizationError(
            "Access denied."
        )

    def logout(self, user_id):

        user = self.get_current_user(user_id)

        self.audit_service.record(
            action="LOGOUT",
            user_id=user.id,
            description="User logged out"
        )