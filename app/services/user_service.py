import re

from app.extensions import db
from app.models import User
from app.repositories import UserRepository

from app.services.base_service import BaseService
from app.services.auth_service import AuthService
from app.services.audit_service import AuditService

from app.exceptions import (
    ValidationError,
    DuplicateError,
    AuthorizationError,
    AuthenticationError,
    BusinessRuleError
)


class UserService(BaseService):
    """Service responsible for user account management."""

    def __init__(self):
        self.repository = UserRepository()
        self.auth_service = AuthService()
        self.audit_service = AuditService()

    def validate_username(self, username):

        username = self.require_text(
            username, "Username"
        )

        if not re.fullmatch(
            r"[A-Za-z0-9_.-]{3,80}", username
        ):
            raise ValidationError(
                "Invalid username."
            )

        return username

    def validate_email(self, email):

        email = self.require_text(
            email, "Email"
        ).lower()

        if len(email) > 120:
            raise ValidationError(
                "Email is too long."
            )

        if not re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            email
        ):
            raise ValidationError(
                "Invalid email address."
            )

        return email

    def validate_role(self, role):

        if role not in self.auth_service.VALID_ROLES:
            raise ValidationError(
                "Invalid user role."
            )

        return role

    def _get_user(self, user_id):

        return self.require_exists(
            self.repository.get_by_id(user_id),
            "User not found."
        )

    def _protect_last_admin(self, user):

        if user.role == "ADMIN" and user.is_active:

            admins = self.repository.get_by_role(
                "ADMIN"
            )

            active_admins = [
                admin for admin in admins
                if admin.is_active
            ]

            if len(active_admins) <= 1:
                raise BusinessRuleError(
                    "Cannot disable the last active administrator."
                )

    def _create_account(
        self,
        actor_id,
        username,
        email,
        password,
        role
    ):

        actor = self.auth_service.require_staff(
            actor_id
        )

        role = self.validate_role(role)

        if actor.role != "ADMIN" and role != "READER":
            raise AuthorizationError(
                "Only administrators can create staff accounts."
            )

        username = self.validate_username(username)
        email = self.validate_email(email)

        if self.repository.get_by_username(username):
            raise DuplicateError(
                "Username already exists."
            )

        if self.repository.get_by_email(email):
            raise DuplicateError(
                "Email already exists."
            )

        password_hash = self.auth_service.hash_password(
            password
        )

        user = User(
            username=username,
            email=email,
            password_hash=password_hash,
            role=role,
            is_active=True
        )

        self.repository.add(user)

        db.session.flush()

        self.audit_service.log(
            action="USER_CREATED",
            user_id=actor.id,
            description=f"Created user ID: {user.id}"
        )

        return user

    def create_user(
        self,
        actor_id,
        username,
        email,
        password,
        role="LIBRARIAN"
    ):

        if role == "READER":
            raise BusinessRuleError(
                "Reader accounts must be created through ReaderService."
            )

        with self.transaction():

            user = self._create_account(
                actor_id,
                username,
                email,
                password,
                role
            )

        return user

    def get_by_id(self, actor_id, user_id):

        actor = self.auth_service.get_current_user(
            actor_id
        )

        if actor.role != "ADMIN" and actor.id != user_id:
            raise AuthorizationError(
                "Access denied."
            )

        return self._get_user(user_id)

    def get_all(self, actor_id):

        self.auth_service.require_admin(actor_id)

        return self.repository.get_all()

    def get_by_role(self, actor_id, role):

        self.auth_service.require_admin(actor_id)

        role = self.validate_role(role)

        return self.repository.get_by_role(role)

    def get_active_users(self, actor_id):

        self.auth_service.require_admin(actor_id)

        return self.repository.get_active_users()

    def get_inactive_users(self, actor_id):

        self.auth_service.require_admin(actor_id)

        return self.repository.get_inactive_users()

    def change_password(
        self,
        actor_id,
        current_password,
        new_password
    ):

        with self.transaction():

            user = self.auth_service.get_current_user(
                actor_id
            )

            if not self.auth_service.verify_password(
                user.password_hash,
                current_password
            ):
                raise AuthenticationError(
                    "Current password is incorrect."
                )

            user.password_hash = (
                self.auth_service.hash_password(
                    new_password
                )
            )

            self.audit_service.log(
                action="PASSWORD_CHANGED",
                user_id=user.id,
                description="User changed own password"
            )

        return user

    def reset_password(
        self,
        actor_id,
        user_id,
        new_password
    ):

        with self.transaction():

            self.auth_service.require_admin(actor_id)

            user = self._get_user(user_id)

            user.password_hash = (
                self.auth_service.hash_password(
                    new_password
                )
            )

            self.audit_service.log(
                action="PASSWORD_RESET",
                user_id=actor_id,
                description=f"Reset password for user ID: {user_id}"
            )

        return user

    def change_role(self, actor_id, user_id, new_role):

        with self.transaction():

            self.auth_service.require_admin(actor_id)

            user = self._get_user(user_id)

            new_role = self.validate_role(new_role)

            if user.role == new_role:
                return user

            if user.role == "READER" or new_role == "READER":
                raise BusinessRuleError(
                    "Reader role conversion is not supported."
                )

            self._protect_last_admin(user)

            old_role = user.role
            user.role = new_role

            self.audit_service.log(
                action="USER_ROLE_CHANGED",
                user_id=actor_id,
                description=(
                    f"User ID: {user_id}; "
                    f"{old_role} -> {new_role}"
                )
            )

        return user

    def activate_user(self, actor_id, user_id):

        with self.transaction():

            self.auth_service.require_admin(actor_id)

            user = self._get_user(user_id)

            if not user.is_active:

                user.is_active = True

                self.audit_service.log(
                    action="USER_ACTIVATED",
                    user_id=actor_id,
                    description=f"Activated user ID: {user_id}"
                )

        return user

    def deactivate_user(self, actor_id, user_id):

        with self.transaction():

            self.auth_service.require_admin(actor_id)

            user = self._get_user(user_id)

            if actor_id == user_id:
                raise BusinessRuleError(
                    "Cannot deactivate your own account."
                )

            self._protect_last_admin(user)

            if user.is_active:

                user.is_active = False

                self.audit_service.log(
                    action="USER_DEACTIVATED",
                    user_id=actor_id,
                    description=f"Deactivated user ID: {user_id}"
                )

        return user