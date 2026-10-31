"""Kernel errors. Each carries the HTTP status the API maps it to."""


class KernelError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.code)
        self.message = message or self.code


class NotAuthenticated(KernelError):
    status_code = 401
    code = "not_authenticated"


class PermissionDenied(KernelError):
    status_code = 403
    code = "permission_denied"


class StepUpRequired(KernelError):
    status_code = 403
    code = "step_up_required"


class NotFound(KernelError):
    status_code = 404
    code = "not_found"


class Conflict(KernelError):
    status_code = 409
    code = "conflict"


class ValidationFailed(KernelError):
    status_code = 422
    code = "validation_failed"


class MissingExplanation(ValidationFailed):
    code = "missing_explanation"


class UndeclaredAction(ValidationFailed):
    code = "undeclared_action"


class TooManyAttempts(KernelError):
    status_code = 429
    code = "too_many_attempts"


class SecurityCheckUnavailable(KernelError):
    """A security step could not run, so the operation is denied (fail closed)."""

    status_code = 503
    code = "security_check_unavailable"


class BudgetExceeded(KernelError):
    status_code = 503
    code = "budget_exceeded"


class ProviderUnavailable(KernelError):
    status_code = 503
    code = "provider_unavailable"


class GraphUnavailable(KernelError):
    status_code = 503
    code = "graph_unavailable"
