"""Errors of the application layer: who may do what, and what exists for whom. The HTTP
adapter translates them (403, 404, 503) in one place; the use cases never mention a status code."""


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


class IdempotencyKeyReused(Exception):
    """The same owner sent an Idempotency-Key it already used with another request body (422)."""

    def __init__(self, message: str = "this Idempotency-Key was already used with another request body") -> None:
        super().__init__(message)
        self.message = message


class DependencyUnavailable(Exception):
    """A dependency the service needs (the database) did not answer: alive, but not ready (503)."""

    def __init__(self, dependency: str) -> None:
        self.dependency = dependency
        self.message = f"{dependency} is not reachable"
        super().__init__(self.message)
