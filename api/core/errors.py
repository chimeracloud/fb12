"""The error envelope every failure uses.

{"error": {"code": "...", "message": "...", "upstream_status": 429}}

Codes in the contract: UPSTREAM_ERROR, NOT_FOUND, INVALID_INPUT, NO_RESULT_YET.
Two more are needed in practice and recorded in the README: UNAUTHENTICATED
(401, no detail) and INTERNAL_ERROR (500, an unexpected exception).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("fb12.errors")


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, upstream_status: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.upstream_status = upstream_status


def error_body(code: str, message: str, upstream_status: int | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if upstream_status is not None:
        error["upstream_status"] = upstream_status
    return {"error": error}


def error_response(status_code: int, code: str, message: str, upstream_status: int | None = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_body(code, message, upstream_status))


def _describe_validation(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p not in ("body",))
        parts.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
    return "Invalid input. " + "; ".join(parts) if parts else "Invalid input."


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.upstream_status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(400, "INVALID_INPUT", _describe_validation(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return error_response(404, "NOT_FOUND", f"No such route: {request.method} {request.url.path}")
        if exc.status_code == 405:
            return error_response(405, "INVALID_INPUT", f"{request.method} is not allowed on {request.url.path}")
        return error_response(exc.status_code, "INTERNAL_ERROR", str(exc.detail))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unexpected error on %s %s", request.method, request.url.path)
        return error_response(
            500,
            "INTERNAL_ERROR",
            f"FB12 hit an unexpected error ({type(exc).__name__}) on {request.method} {request.url.path}. The log has the trace.",
        )
