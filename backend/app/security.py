"""Cabeceras de seguridad para todas las respuestas de la API."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response


def add_security_headers(app: FastAPI, es_local: bool) -> None:
    @app.middleware("http")
    async def cabeceras(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        if not es_local:  # /docs necesita scripts en local
            resp.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
            resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return resp
