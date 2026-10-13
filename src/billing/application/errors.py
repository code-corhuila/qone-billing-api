"""Errors of the application layer: who may do what, and what exists for whom. The HTTP
adapter translates them (403, 404) in one place; the use cases never mention a status code."""


class Forbidden(Exception):
    """The caller's role may not perform the operation."""

    def __init__(self, message: str = "this role may not perform the operation") -> None:
        super().__init__(message)
        self.message = message


class NotFound(Exception):
    """The resource does not exist, or belongs to another student and revealing it would leak
    data (D-03): both look the same from outside."""

    def __init__(self, message: str = "resource not found") -> None:
        super().__init__(message)
        self.message = message
