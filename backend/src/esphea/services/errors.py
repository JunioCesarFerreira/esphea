"""Application-level errors, translated to HTTP responses by the API layer."""


class NotFoundError(LookupError):
    pass


class ConflictError(RuntimeError):
    pass


class InvalidRequestError(ValueError):
    """A well-formed request that cannot be honoured for the targeted resource."""
