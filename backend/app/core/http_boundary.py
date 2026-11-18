import logging
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse

logger = logging.getLogger("uvicorn.error").getChild("http")
JSON_LIMIT = 256 * 1024


class HttpBoundary:
    def __init__(self, app, production=False):
        self.app = app
        self.production = production

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid4().hex
        started = perf_counter()
        status = 500
        sent_headers = False
        path = scope["path"]
        method = scope["method"]

        async def respond(message):
            nonlocal status, sent_headers
            if message["type"] == "http.response.start":
                status = message["status"]
                sent_headers = True
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                headers["X-Frame-Options"] = "DENY"
                if self.production:
                    headers["Strict-Transport-Security"] = "max-age=31536000"
            await send(message)

        try:
            upload = method == "PUT" and path.startswith("/api/v1/documents/") and path.endswith("/uploads/content")
            if method in {"POST", "PUT", "PATCH", "DELETE"} and not upload:
                body = bytearray()
                while True:
                    part = await receive()
                    if part["type"] == "http.disconnect":
                        return
                    content = part.get("body", b"")
                    if len(content) + len(body) > JSON_LIMIT:
                        return await JSONResponse({"detail": "Request body too large"}, 413)(scope, receive, respond)
                    body.extend(content)
                    if not part.get("more_body", False):
                        break
                original = receive
                sent = False

                async def replay():
                    nonlocal sent
                    if sent:
                        return await original()
                    sent = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}

                receive = replay
            await self.app(scope, receive, respond)
        except Exception as exc:
            logger.error("request_id=%s failure_type=%s", request_id, type(exc).__name__)
            if sent_headers:
                raise RuntimeError("Response stream failed") from None
            await JSONResponse({"detail": "The server could not complete the request."}, 500)(scope, receive, respond)
        finally:
            route = getattr(scope.get("route"), "path", "unmatched")
            logger.info("request_id=%s method=%s route=%s status=%s duration_ms=%.1f",
                        request_id, method, route, status, (perf_counter() - started) * 1000)
