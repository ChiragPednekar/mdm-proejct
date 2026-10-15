"""Domain exceptions and centralized FastAPI exception handlers.

Every error response has the shape::

    {"error": {"code": "...", "message": "...", "details": ...}}
"""
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException


class DomainError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "bad_request"

    def __init__(self, message: str, details: Any = None):
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(DomainError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class BusinessRuleError(DomainError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "business_rule_violation"


class InvalidTransitionError(ConflictError):
    code = "invalid_state_transition"


class InsufficientStockError(ConflictError):
    code = "insufficient_stock"


class ModelUnavailableError(DomainError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "model_unavailable"


class AuthError(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


class ForbiddenError(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


def _body(code: str, message: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


# Friendly messages for constraint names, so database errors are safe to show.
_CONSTRAINT_MESSAGES = {
    "products_serial_number_key": "A product with this serial number is already registered.",
    "customers_email_key": "A customer with this email already exists.",
    "parts_part_number_key": "A part with this part number already exists.",
    "technicians_email_key": "A technician with this email already exists.",
    "uq_warranties_one_manufacturer_per_product": "This product already has a manufacturer warranty.",
    "uq_product_models_manufacturer_model": "This manufacturer already has a model with that name.",
    "ck_parts_stock_non_negative": "Stock quantity cannot become negative.",
    "repair_parts_pkey": "The same part cannot appear twice in one repair.",
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_body("validation_error", "Request validation failed.", details),
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError):
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        message = _CONSTRAINT_MESSAGES.get(constraint or "", "The request conflicts with existing data.")
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=_body("integrity_error", message, {"constraint": constraint}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content=_body("http_error", str(exc.detail)))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):  # pragma: no cover - safety net
        import logging

        logging.getLogger("app").exception("Unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_body("internal_error", "An unexpected error occurred."),
        )
