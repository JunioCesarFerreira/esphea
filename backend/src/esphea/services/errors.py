"""Application-level errors, translated to HTTP responses by the API layer."""


class NotFoundError(LookupError):
    pass


class ConflictError(RuntimeError):
    pass
