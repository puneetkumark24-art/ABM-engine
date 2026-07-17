"""
observability.py — Sprint 1 (S1-02): structured logging, request correlation,
health/readiness probes, and Prometheus metrics. Fixes the audit's 0/10
Monitoring and Observability and 2/10 Logging.

- JSON structured logs with a request-id correlation field.
- RequestContextMiddleware: assigns/propagates X-Request-ID, times each request,
  records metrics.
- /health/live   liveness (process up).
- /health/ready  readiness (DB reachable) — for K8s readiness probes / LBs.
- /metrics       Prometheus text exposition (request counts, latency, in-flight).

Zero external deps (stdlib + FastAPI). An OpenTelemetry exporter can be added
later behind the same middleware without changing callers.
"""
from __future__ import annotations
import json
import logging
import time
import uuid
from contextvars import ContextVar
from collections import defaultdict
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse, JSONResponse

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


# ── structured JSON logging ──────────────────────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for k, v in getattr(record, "extra_fields", {}).items():
            payload[k] = v
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())


# ── metrics registry (Prometheus text) ──────────────────────
class _Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self.requests_total: dict[tuple, int] = defaultdict(int)   # (method,path,status)->n
        self.latency_sum: dict[tuple, float] = defaultdict(float)
        self.latency_count: dict[tuple, int] = defaultdict(int)
        self.in_flight = 0

    def observe(self, method: str, path: str, status: int, seconds: float) -> None:
        with self._lock:
            key = (method, path, str(status))
            self.requests_total[key] += 1
            lk = (method, path)
            self.latency_sum[lk] += seconds
            self.latency_count[lk] += 1

    def prometheus(self) -> str:
        lines = ["# HELP drip_requests_total Total HTTP requests",
                 "# TYPE drip_requests_total counter"]
        with self._lock:
            for (m, p, s), n in self.requests_total.items():
                lines.append(f'drip_requests_total{{method="{m}",path="{p}",status="{s}"}} {n}')
            lines += ["# HELP drip_request_latency_seconds Request latency sum/count",
                      "# TYPE drip_request_latency_seconds summary"]
            for (m, p), tot in self.latency_sum.items():
                cnt = self.latency_count[(m, p)]
                lines.append(f'drip_request_latency_seconds_sum{{method="{m}",path="{p}"}} {tot:.6f}')
                lines.append(f'drip_request_latency_seconds_count{{method="{m}",path="{p}"}} {cnt}')
            lines += ["# HELP drip_in_flight_requests In-flight requests",
                      "# TYPE drip_in_flight_requests gauge",
                      f"drip_in_flight_requests {self.in_flight}"]
        return "\n".join(lines) + "\n"


metrics = _Metrics()
_log = logging.getLogger("drip.http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(rid)
        metrics.in_flight += 1
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["x-request-id"] = rid
            return response
        finally:
            dur = time.perf_counter() - start
            metrics.in_flight -= 1
            # normalize path (strip ids) so metric cardinality stays bounded
            path = _norm(request.url.path)
            metrics.observe(request.method, path, status, dur)
            _log.info("request", extra={"extra_fields": {
                "method": request.method, "path": request.url.path,
                "status": status, "ms": round(dur * 1000, 1)}})
            request_id_var.reset(token)


def _norm(path: str) -> str:
    parts = []
    for seg in path.split("/"):
        if len(seg) >= 16 or (seg.isalnum() and any(c.isdigit() for c in seg) and len(seg) > 8):
            parts.append(":id")
        else:
            parts.append(seg)
    return "/".join(parts) or "/"


def register(app, engine) -> None:
    """Attach middleware + health/metrics endpoints to a FastAPI app."""
    app.add_middleware(RequestContextMiddleware)

    @app.get("/health/live", include_in_schema=False)
    def live():
        return {"status": "alive"}

    @app.get("/health/ready", include_in_schema=False)
    def ready():
        from sqlalchemy import text
        try:
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            return {"status": "ready", "db": "ok"}
        except Exception as e:
            return JSONResponse({"status": "not-ready", "db": str(e)[:120]}, status_code=503)

    @app.get("/metrics", include_in_schema=False)
    def prom():
        return PlainTextResponse(metrics.prometheus(), media_type="text/plain; version=0.0.4")
