class LibraManagerError(Exception):
    """Base exception for LibraManager."""


class ValidationError(LibraManagerError):
    """Invalid input data."""


class NotFoundError(LibraManagerError):
    """Requested object does not exist."""


class DuplicateError(LibraManagerError):
    """Object already exists."""


class AuthenticationError(LibraManagerError):
    """Invalid authentication credentials."""


class AuthorizationError(LibraManagerError):
    """Insufficient user permissions."""


class InactiveAccountError(AuthorizationError):
    """User account is inactive."""


class BusinessRuleError(LibraManagerError):
    """Business rule violation."""


class CopyUnavailableError(BusinessRuleError):
    """Book copy is unavailable."""


class LoanLimitExceededError(BusinessRuleError):
    """Reader has reached the loan limit."""


class ReservationLimitExceededError(BusinessRuleError):
    """Reader has reached the reservation limit."""


class LoanAlreadyReturnedError(BusinessRuleError):
    """Loan has already been returned."""


class ReservationAlreadyExistsError(BusinessRuleError):
    """An active reservation already exists."""


class InvalidPaymentError(BusinessRuleError):
    """Payment does not meet business requirements."""


class DatabaseError(LibraManagerError):
    """Database operation failed."""