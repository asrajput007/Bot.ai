class GrowthOSError(Exception):
    pass


class ConfigError(GrowthOSError):
    pass


class UnknownClientError(GrowthOSError):
    pass


class UnknownOperatorError(GrowthOSError):
    pass


class AccessDeniedError(GrowthOSError):
    pass


class NotFoundError(GrowthOSError):
    pass


class InvalidInput(GrowthOSError):
    pass


class DuplicateRunError(GrowthOSError):
    pass


class GuardrailViolation(GrowthOSError):
    def __init__(self, issues):
        self.issues = list(issues)
        super().__init__("; ".join(self.issues))


class BudgetExceededError(GrowthOSError):
    pass


class LLMError(GrowthOSError):
    pass


class LLMOutputError(LLMError):
    pass
