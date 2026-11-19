"""Standardised error responses + exception handlers.

APP-R-001 / APP-R-020: FastAPI's default HTTP 422 is replaced by HTTP 400 with stable codes:
  MALFORMED_JSON, REQUEST_SCHEMA_INVALID (APP-R-001) and INVALID_DOMAIN_VALUE (APP-R-020).
Validation runs before any route/business code, so no business operation executes.
"""
import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.observability.event_logger import log_event
from app.observability.tracing import current

logger = logging.getLogger("minishop.errors")

# pydantic error types that mean "well-formed but invalid domain value" (APP-R-020)
DOMAIN_ERROR_TYPES = {
    "greater_than", "greater_than_equal", "less_than", "less_than_equal", "multiple_of",
    "value_error", "assertion_error", "string_too_short", "string_too_long",
    "too_short", "too_long", "string_pattern_mismatch",
}


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        event_type: str | None = None,
        severity: str = "WARNING",
        rule_id: str | None = None,
        context: dict | None = None,
        details: dict | None = None,
        headers: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.event_type = event_type
        self.severity = severity
        self.rule_id = rule_id
        self.context = context or {}
        self.details = details
        self.headers = headers


def ok(data=None, status_code: int = 200, headers: dict | None = None, **extra) -> JSONResponse:
    """Standard success envelope. Serialization is traced as its own span."""
    from app.observability.tracing import span
    from app.utils.serialization import public

    ctx = current()
    with span("response_serialization", "serialization"):
        body = {"success": True, "data": public(data), "request_id": ctx.request_id if ctx else None, **extra}
        return JSONResponse(status_code=status_code, content=body, headers=headers)


def error_response(status_code: int, code: str, message: str, details: dict | None = None,
                   headers: dict | None = None) -> JSONResponse:
    ctx = current()
    error = {"code": code, "message": message}
    if details:
        error["details"] = details
    body = {"success": False, "error": error, "request_id": ctx.request_id if ctx else None}
    return JSONResponse(status_code=status_code, content=body, headers=headers)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    if exc.event_type:
        await log_event(
            exc.event_type, exc.severity, rule_id=exc.rule_id, error_code=exc.code,
            http_status=exc.status_code, context=exc.context,
        )
    return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Only loc/type/msg are kept: never echo submitted values (could contain secrets).
    problems = [
        {"loc": [str(p) for p in e.get("loc", ())], "type": e.get("type"), "msg": e.get("msg")}
        for e in exc.errors()
    ]
    types = {p["type"] for p in problems}
    if "json_invalid" in types:
        code, rule, event, msg = "MALFORMED_JSON", "APP-R-001", "REQUEST_VALIDATION_FAILURE", "Request body is not valid JSON."
    elif types & DOMAIN_ERROR_TYPES:
        code, rule, event, msg = (
            "INVALID_DOMAIN_VALUE", "APP-R-020", "DOMAIN_VALIDATION_FAILURE",
            "One or more values are invalid. Correct the input and resubmit.",
        )
    else:
        code, rule, event, msg = (
            "REQUEST_SCHEMA_INVALID", "APP-R-001", "REQUEST_VALIDATION_FAILURE",
            "Request does not match the expected schema.",
        )
    await log_event(event, "WARNING", rule_id=rule, error_code=code, http_status=400,
                    context={"problems": problems[:10]})
    return error_response(400, code, msg, {"problems": problems[:10]})


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "AUTH_REQUIRED", 403: "FORBIDDEN"}
    code = codes.get(exc.status_code, "HTTP_ERROR")
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return error_response(exc.status_code, code, message, headers=getattr(exc, "headers", None))


async def log_unhandled(exc: Exception) -> None:
    logger.error("unhandled exception", exc_info=exc)  # traceback only in server log
    await log_event("UNHANDLED_EXCEPTION", "ERROR", error_code="INTERNAL_ERROR",
                    exception_type=type(exc).__name__, http_status=500)


def internal_error_response() -> JSONResponse:
    return error_response(500, "INTERNAL_ERROR", "An unexpected error occurred.")
