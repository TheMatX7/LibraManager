import pytest

from app.exceptions import (
    LibraManagerError,
    BusinessRuleError,
    ValidationError,
    NotFoundError,
    AuthorizationError,
    InactiveAccountError,
    CopyUnavailableError,
    LoanLimitExceededError,
    InvalidPaymentError
)


def test_validation_error():
    with pytest.raises(LibraManagerError):
        raise ValidationError("Invalid data")


def test_not_found_error():
    with pytest.raises(NotFoundError):
        raise NotFoundError("Book not found")


def test_unavailable_copy():
    with pytest.raises(BusinessRuleError):
        raise CopyUnavailableError("Copy unavailable")


def test_loan_limit():
    with pytest.raises(BusinessRuleError):
        raise LoanLimitExceededError("Loan limit exceeded")


def test_inactive_account():
    with pytest.raises(AuthorizationError):
        raise InactiveAccountError("Account inactive")


def test_invalid_payment():
    with pytest.raises(BusinessRuleError):
        raise InvalidPaymentError("Invalid payment")


def test_exception_message():
    error = ValidationError("Invalid ISBN")

    assert str(error) == "Invalid ISBN"