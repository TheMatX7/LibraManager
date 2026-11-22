import unicodedata

from app.extensions import db
from app.models import Author
from app.repositories import AuthorRepository

from app.services.base_service import BaseService
from app.services.auth_service import AuthService
from app.services.audit_service import AuditService

from app.exceptions import (
    ValidationError,
    BusinessRuleError
)


class AuthorService(BaseService):
    """Service responsible for book authors."""

    def __init__(self):
        self.repository = AuthorRepository()
        self.auth_service = AuthService()
        self.audit_service = AuditService()

    @staticmethod
    def normalize_name(name):

        return unicodedata.normalize(
            "NFC", name.strip()
        ).casefold()

    def validate_name(self, value, field_name):

        value = self.require_text(
            value, field_name
        )

        value = unicodedata.normalize(
            "NFC", value
        )

        if len(value) > 100:

            raise ValidationError(
                f"{field_name} cannot exceed 100 characters."
            )

        if not all(
            char.isalpha() or char in " -.'’"
            for char in value
        ):

            raise ValidationError(
                f"Invalid {field_name.lower()}."
            )

        if not any(
            char.isalpha() for char in value
        ):

            raise ValidationError(
                f"Invalid {field_name.lower()}."
            )

        return value

    def _get_author(self, author_id):

        return self.require_exists(
            self.repository.get_by_id(author_id),
            "Author not found."
        )

    def create_author(
        self,
        actor_id,
        first_name,
        last_name
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

            author = Author(
                first_name=first_name,
                last_name=last_name
            )

            self.repository.add(author)

            db.session.flush()

            self.audit_service.log(
                action="AUTHOR_CREATED",
                user_id=actor_id,
                description=(
                    f"Created author ID: {author.id}"
                )
            )

        return author

    def get_by_id(self, actor_id, author_id):

        self.auth_service.get_current_user(
            actor_id
        )

        return self._get_author(author_id)

    def get_all(self, actor_id):

        self.auth_service.get_current_user(
            actor_id
        )

        return self.repository.get_all()

    def get_by_name(
        self,
        actor_id,
        first_name,
        last_name
    ):

        self.auth_service.get_current_user(
            actor_id
        )

        first_name = self.validate_name(
            first_name, "First name"
        )

        last_name = self.validate_name(
            last_name, "Last name"
        )

        first_name = self.normalize_name(
            first_name
        )

        last_name = self.normalize_name(
            last_name
        )

        return [
            author
            for author in self.repository.get_all()
            if (
                self.normalize_name(
                    author.first_name
                ) == first_name
                and
                self.normalize_name(
                    author.last_name
                ) == last_name
            )
        ]

    def get_sorted(self, actor_id):

        self.auth_service.get_current_user(
            actor_id
        )

        return sorted(
            self.repository.get_all(),
            key=lambda author: (
                self.normalize_name(author.last_name),
                self.normalize_name(author.first_name),
                author.id
            )
        )

    def search(self, actor_id, query):

        self.auth_service.get_current_user(
            actor_id
        )

        query = self.require_text(
            query, "Search query"
        )

        if len(query) > 201:

            raise ValidationError(
                "Search query is too long."
            )

        query = self.normalize_name(query)

        result = []

        for author in self.repository.get_all():

            first_name = self.normalize_name(
                author.first_name
            )

            last_name = self.normalize_name(
                author.last_name
            )

            full_name = (
                f"{first_name} {last_name}"
            )

            reversed_name = (
                f"{last_name} {first_name}"
            )

            if (
                query in full_name
                or query in reversed_name
            ):

                result.append(author)

        return result

    def update_author(
        self,
        actor_id,
        author_id,
        first_name,
        last_name
    ):

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            author = self._get_author(
                author_id
            )

            first_name = self.validate_name(
                first_name, "First name"
            )

            last_name = self.validate_name(
                last_name, "Last name"
            )

            author.first_name = first_name
            author.last_name = last_name

            self.audit_service.log(
                action="AUTHOR_UPDATED",
                user_id=actor_id,
                description=(
                    f"Updated author ID: {author.id}"
                )
            )

        return author

    def delete_author(
        self,
        actor_id,
        author_id
    ):

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            author = self._get_author(
                author_id
            )

            if author.books:

                raise BusinessRuleError(
                    "Cannot delete an author associated with books."
                )

            self.repository.delete(author)

            self.audit_service.log(
                action="AUTHOR_DELETED",
                user_id=actor_id,
                description=(
                    f"Deleted author ID: {author_id}"
                )
            )

        return True

    def get_books(
        self,
        actor_id,
        author_id,
        include_archived=False
    ):

        self.auth_service.get_current_user(
            actor_id
        )

        if type(include_archived) is not bool:

            raise ValidationError(
                "Include archived must be a boolean."
            )

        if include_archived:

            self.auth_service.require_staff(
                actor_id
            )

        author = self._get_author(
            author_id
        )

        if include_archived:

            return list(author.books)

        return [
            book
            for book in author.books
            if not book.is_archived
        ]

    def count(self, actor_id):

        self.auth_service.get_current_user(
            actor_id
        )

        return self.repository.count()

    def count_books(
        self,
        actor_id,
        author_id,
        include_archived=False
    ):

        return len(
            self.get_books(
                actor_id,
                author_id,
                include_archived
            )
        )