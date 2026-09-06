"""Errors crossing application boundaries; messages must not contain secrets."""


class ConfigurationError(ValueError):
    pass


class AuthenticationError(ConfigurationError):
    pass


class ProviderError(RuntimeError):
    pass


class ProviderRateLimitError(ProviderError):
    pass


class ProviderUnavailableError(ProviderError):
    pass


class StorageError(RuntimeError):
    pass


class DataUnavailable(StorageError):
    pass


class QueryLimitExceeded(DataUnavailable):
    pass
