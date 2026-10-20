"""Loopback session protection for the desktop/browser launcher."""

import json
import secrets

from fastapi import HTTPException
from starlette.responses import HTMLResponse, JSONResponse

from .uploads import MAX_UPLOAD_BYTES
from ..knowledge.documents import MAX_FILE_BYTES


class RequestSizeLimit:
    """Bound incoming bodies before multipart parsing/spooling."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = MAX_UPLOAD_BYTES + 16 * 1024 ** 2 if scope["path"] == "/api/uploads" else 2 * 1024 ** 2
        if scope["path"] == "/api/knowledge/uploads":
            limit = MAX_FILE_BYTES + 1024 ** 2
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = limit + 1
        if length > limit:
            return await JSONResponse({"detail": "Request exceeds the local import limit; link large folders instead."}, 413)(scope, receive, send)
        total = 0

        async def bounded_receive():
            nonlocal total
            event = await receive()
            total += len(event.get("body", b""))
            if total > limit:
                raise HTTPException(status_code=413, detail="Request body exceeds the limit.")
            return event

        return await self.app(scope, bounded_receive, send)


def install_security(app, index_path, enabled=False):
    app.add_middleware(RequestSizeLimit)
    token = secrets.token_urlsafe(32)
    app.state.session_token = token

    @app.middleware("http")
    async def guard(request, call_next):
        if enabled:
            host = request.url.hostname
            if host not in {"localhost", "127.0.0.1", "::1"}:
                return JSONResponse({"detail": "Only loopback hosts are accepted."}, 403)
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Cross-origin requests are forbidden."}, 403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Cross-site requests are forbidden."}, 403)
            if request.url.path not in {"/", "/index.html", "/healthz"}:
                supplied = request.headers.get("x-spatialmind-token", "") or request.cookies.get("spatialmind_session", "")
                if not secrets.compare_digest(supplied, token):
                    return JSONResponse({"detail": "Open the local Studio window to start a session."}, 401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if (request.url.path.startswith("/artifacts/") or
                (response.headers.get("content-type", "").startswith("text/html") and
                 request.url.path not in {"/", "/index.html"})):
            response.headers["Content-Security-Policy"] = "sandbox allow-scripts allow-downloads"
        return response

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    def index():
        content = index_path.read_text(encoding="utf-8")
        # Only the local, same-origin application can read this bootstrap page.
        content = content.replace("/* STUDIO_SESSION */", "window.STUDIO_TOKEN = %s;" % json.dumps(token))
        response = HTMLResponse(content, headers={"Cache-Control": "no-store"})
        response.set_cookie("spatialmind_session", token, httponly=True, samesite="strict")
        return response
