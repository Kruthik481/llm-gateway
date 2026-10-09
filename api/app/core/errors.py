from collections.abc import Mapping
from typing import Any


def _default_type(status: int) -> str:
    if status == 401:
        return "authentication_error"
    if status == 429:
        return "rate_limit_error"
    if status >= 500:
        return "api_error"
    return "invalid_request_error"


class GatewayError(Exception):
    """An error returned to the client in OpenAI's error shape."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        type_: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.type = type_ or _default_type(status)
        self.headers: dict[str, str] = dict(headers or {})

    def body(self) -> dict[str, Any]:
        return {"error": {"message": self.message, "type": self.type, "code": self.code}}
