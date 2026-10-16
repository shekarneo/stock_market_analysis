from __future__ import annotations


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ConfigValidationError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("INVALID_CONFIG", message, 422)


class SsrfError(AppError):
    def __init__(self, message: str = "URL is not allowed") -> None:
        super().__init__("SSRF_REFUSED", message, 400)


class ModeForbidden(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("MODE_FORBIDDEN", message, 403)


class LiveOrderDisabled(AppError):
    def __init__(self) -> None:
        super().__init__(
            "LIVE_ORDERS_DISABLED",
            "Live order placement is not enabled.",
            403,
        )


class SourceDisabled(AppError):
    def __init__(self) -> None:
        super().__init__(
            "SOURCE_DISABLED",
            "A disabled news source is not fetched.",
            409,
        )


class ConnectorNotImplemented(AppError):
    def __init__(self) -> None:
        super().__init__(
            "CONNECTOR_NOT_IMPLEMENTED",
            "News connectors are not implemented in M0.",
            501,
        )
