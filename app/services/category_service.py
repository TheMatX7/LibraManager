import unicodedata

from app.extensions import db
from app.models import Category

from app.repositories import (
    CategoryRepository,
    BookRepository
)

from app.services.base_service import BaseService
from app.services.auth_service import AuthService
from app.services.audit_service import AuditService

from app.exceptions import (
    ValidationError,
    DuplicateError,
    BusinessRuleError
)


class CategoryService(BaseService):
    """Service responsible for book categories."""

    def __init__(self):
        self.repository = CategoryRepository()
        self.book_repository = BookRepository()
        self.auth_service = AuthService()
        self.audit_service = AuditService()

    @staticmethod
    def normalize_name(name):

        return unicodedata.normalize(
            "NFC", name.strip()
        ).casefold()

    def validate_name(self, name):

        name = self.require_text(
            name, "Category name"
        )

        name = unicodedata.normalize(
            "NFC", name
        )

        if len(name) > 100:
            raise ValidationError(
                "Category name cannot exceed 100 characters."
            )

        return name

    def validate_description(self, description):

        if description is None:
            return None

        if not isinstance(description, str):
            raise ValidationError(
                "Description must be a string."
            )

        description = description.strip()

        if len(description) > 2000:
            raise ValidationError(
                "Description cannot exceed 2000 characters."
            )

        return description or None

    def _get_category(self, category_id):

        return self.require_exists(
            self.repository.get_by_id(category_id),
            "Category not found."
        )

    def _check_duplicate(self, name, exclude_id=None):

        normalized_name = self.normalize_name(name)

        for category in self.repository.get_all():

            if category.id == exclude_id:
                continue

            if (
                self.normalize_name(category.name)
                == normalized_name
            ):
                raise DuplicateError(
                    "Category already exists."
                )

    def create_category(
        self,
        actor_id,
        name,
        description=None
    ):

        with self.transaction():

            self.auth_service.require_staff(actor_id)

            name = self.validate_name(name)

            description = self.validate_description(
                description
            )

            self._check_duplicate(name)

            category = Category(
                name=name,
                description=description
            )

            self.repository.add(category)

            db.session.flush()

            self.audit_service.log(
                action="CATEGORY_CREATED",
                user_id=actor_id,
                description=(
                    f"Created category ID: {category.id}"
                )
            )

        return category

    def get_by_id(self, actor_id, category_id):

        self.auth_service.get_current_user(actor_id)

        return self._get_category(category_id)

    def get_by_name(self, actor_id, name):

        self.auth_service.get_current_user(actor_id)

        name = self.validate_name(name)

        normalized_name = self.normalize_name(name)

        for category in self.repository.get_all():

            if (
                self.normalize_name(category.name)
                == normalized_name
            ):
                return category

        return self.require_exists(
            None,
            "Category not found."
        )

    def get_all(self, actor_id):

        self.auth_service.get_current_user(actor_id)

        return self.repository.get_all()

    def get_sorted(self, actor_id):

        self.auth_service.get_current_user(actor_id)

        return sorted(
            self.repository.get_all(),
            key=lambda category: (
                self.normalize_name(category.name),
                category.id
            )
        )

    def search(self, actor_id, query):

        self.auth_service.get_current_user(actor_id)

        query = self.require_text(
            query, "Search query"
        )

        if len(query) > 100:
            raise ValidationError(
                "Search query is too long."
            )

        query = self.normalize_name(query)

        return [
            category
            for category in self.repository.get_all()
            if query in self.normalize_name(category.name)
        ]

    def update_category(
        self,
        actor_id,
        category_id,
        name,
        description=None
    ):

        with self.transaction():

            self.auth_service.require_staff(actor_id)

            category = self._get_category(category_id)

            name = self.validate_name(name)

            description = self.validate_description(
                description
            )

            self._check_duplicate(
                name,
                exclude_id=category.id
            )

            category.name = name
            category.description = description

            self.audit_service.log(
                action="CATEGORY_UPDATED",
                user_id=actor_id,
                description=(
                    f"Updated category ID: {category.id}"
                )
            )

        return category

    def delete_category(self, actor_id, category_id):

        with self.transaction():

            self.auth_service.require_staff(actor_id)

            category = self._get_category(category_id)

            books = self.book_repository.get_by_category(
                category.id
            )

            if books:
                raise BusinessRuleError(
                    "Cannot delete a category containing books."
                )

            self.repository.delete(category)

            self.audit_service.log(
                action="CATEGORY_DELETED",
                user_id=actor_id,
                description=(
                    f"Deleted category ID: {category_id}"
                )
            )

        return True

    def count(self, actor_id):

        self.auth_service.get_current_user(actor_id)

        return self.repository.count()

    def count_books(self, actor_id, category_id):

        self.auth_service.require_staff(actor_id)

        category = self._get_category(category_id)

        return len(
            self.book_repository.get_by_category(
                category.id
            )
        )