import pytest

from app.extensions import db
from app.models import User, Reader, Book, Author, Category, Copy

from app.repositories import (
    ReaderRepository,
    BookRepository,
    AuthorRepository,
    CategoryRepository,
    CopyRepository
)


@pytest.fixture
def catalog_data(app):

    user = User(
        username="reader1",
        email="reader1@example.com",
        password_hash="test_hash",
        role="READER",
        is_active=True
    )

    category = Category(name="Fantasy")

    author = Author(
        first_name="Andrzej",
        last_name="Sapkowski"
    )

    db.session.add_all([user, category, author])
    db.session.flush()

    reader = Reader(
        user_id=user.id,
        card_number="LIB-001",
        first_name="Jan",
        last_name="Kowalski"
    )

    book = Book(
        title="Wiedzmin",
        isbn="9788375780635",
        category_id=category.id,
        publication_year=1993,
        is_archived=False
    )

    book.authors.append(author)

    db.session.add_all([reader, book])
    db.session.flush()

    copy1 = Copy(
        book_id=book.id,
        inventory_number="INV-001",
        status="AVAILABLE"
    )

    copy2 = Copy(
        book_id=book.id,
        inventory_number="INV-002",
        status="LOANED"
    )

    db.session.add_all([copy1, copy2])
    db.session.commit()

    return {
        "user": user,
        "reader": reader,
        "category": category,
        "author": author,
        "book": book,
        "copy1": copy1,
        "copy2": copy2
    }


def test_reader_by_card(catalog_data):
    repo = ReaderRepository()
    assert repo.get_by_card_number("LIB-001").id == catalog_data["reader"].id


def test_reader_by_user_id(catalog_data):
    repo = ReaderRepository()
    assert repo.get_by_user_id(catalog_data["user"].id) is not None


def test_reader_search(catalog_data):
    repo = ReaderRepository()
    assert len(repo.search("Kowalski")) == 1


def test_book_by_isbn(catalog_data):
    repo = BookRepository()
    assert repo.get_by_isbn("9788375780635").id == catalog_data["book"].id


def test_book_search_title(catalog_data):
    repo = BookRepository()
    assert len(repo.search("Wiedzmin")) == 1


def test_book_search_author(catalog_data):
    repo = BookRepository()
    assert len(repo.search("Sapkowski")) == 1


def test_book_by_category(catalog_data):
    repo = BookRepository()
    assert len(repo.get_by_category(catalog_data["category"].id)) == 1


def test_active_books(catalog_data):
    repo = BookRepository()
    assert len(repo.get_active_books()) == 1


def test_archived_books(catalog_data):
    catalog_data["book"].is_archived = True
    db.session.commit()

    repo = BookRepository()

    assert len(repo.get_archived_books()) == 1
    assert len(repo.get_active_books()) == 0
    assert len(repo.search("Wiedzmin")) == 0


def test_author_search(catalog_data):
    repo = AuthorRepository()
    assert len(repo.search("Sapkowski")) == 1


def test_author_by_name(catalog_data):
    repo = AuthorRepository()
    assert len(repo.get_by_name("Andrzej", "Sapkowski")) == 1


def test_category_by_name(catalog_data):
    repo = CategoryRepository()
    assert repo.get_by_name("Fantasy").id == catalog_data["category"].id


def test_category_sorted(catalog_data):
    repo = CategoryRepository()
    assert repo.get_sorted()[0].name == "Fantasy"


def test_copy_by_inventory_number(catalog_data):
    repo = CopyRepository()
    assert repo.get_by_inventory_number("INV-001") is not None


def test_copies_by_book(catalog_data):
    repo = CopyRepository()
    assert len(repo.get_by_book_id(catalog_data["book"].id)) == 2


def test_available_copies(catalog_data):
    repo = CopyRepository()
    assert len(repo.get_available_copies(catalog_data["book"].id)) == 1


def test_count_available_copies(catalog_data):
    repo = CopyRepository()
    assert repo.count_available_copies(catalog_data["book"].id) == 1


def test_copies_by_status(catalog_data):
    repo = CopyRepository()
    assert len(repo.get_by_status("LOANED")) == 1