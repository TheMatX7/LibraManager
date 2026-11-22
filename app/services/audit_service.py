from app.models import AuditLog

from app.repositories import (
    AuditRepository,
    UserRepository
)

from app.services.base_service import BaseService

from app.exceptions import ValidationError


class AuditService(BaseService):
    """Service responsible for system audit logs."""

    def __init__(self):
        self.repository = AuditRepository()
        self.user_repository = UserRepository()

    def log(self, action, user_id=None, description=None):

        action = self.require_text(action, "Action")

        if len(action) > 100:
            raise ValidationError(
                "Action cannot exceed 100 characters."
            )

        if description is not None:
            if not isinstance(description, str):
                raise ValidationError(
                    "Description must be a string."
                )

        if user_id is not None:
            if type(user_id) is not int or user_id < 1:
                raise ValidationError(
                    "Invalid user identifier."
                )

            self.require_exists(
                self.user_repository.get_by_id(user_id),
                "User not found."
            )

        audit_log = AuditLog(
            user_id=user_id,
            action=action,
            description=description
        )

        self.repository.add(audit_log)

        return audit_log

    def record(self, action, user_id=None, description=None):

        with self.transaction():
            audit_log = self.log(
                action,
                user_id,
                description
            )

        return audit_log

    def get_by_id(self, audit_id):

        return self.require_exists(
            self.repository.get_by_id(audit_id),
            "Audit log not found."
        )

    def get_all(self):

        return self.repository.get_all()

    def get_by_user(self, user_id):

        self.require_exists(
            self.user_repository.get_by_id(user_id),
            "User not found."
        )

        return self.repository.get_by_user(user_id)

    def get_by_action(self, action):

        action = self.require_text(action, "Action")

        return self.repository.get_by_action(action)

    def get_recent(self, limit=50):

        if type(limit) is not int:
            raise ValidationError(
                "Limit must be an integer."
            )

        if limit < 1 or limit > 1000:
            raise ValidationError(
                "Limit must be between 1 and 1000."
            )

        return self.repository.get_recent(limit)

    def count(self):

        return self.repository.count()