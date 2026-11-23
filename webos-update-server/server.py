"""
webOS CE update server (swupdate.webosarchive.org)

Serves CE OTA to OTA Ready 3.x on webOS CE 3.1.0 and later: the device-filtered
release check, signed manifests and payloads (ce_ota.py), plus health and
traffic stats. The 3.0.5-era OMA DM server and OTA Ready 1.x endpoints were
removed on 2026-11-23: 3.0.5 -> 3.1.0 is a Doctor flash, never an OTA.
"""
import logging
import time
from collections import defaultdict, deque
from logging.handlers import RotatingFileHandler
from typing import Optional

from fastapi import FastAPI, Request
import uvicorn

import config
import ce_ota

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Optional persistent access log (survives restarts; journald covers stdout too).
if config.LOG_FILE:
    _fh = RotatingFileHandler(config.LOG_FILE, maxBytes=5_000_000, backupCount=5)
    _fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logging.getLogger().addHandler(_fh)
    logger.info(f"Access log -> {config.LOG_FILE}")

app = FastAPI(
    title="webOS CE update server",
    description="CE OTA for webOS CE 3.1.0 and later",
    version="2.0.0"
)
app.include_router(ce_ota.router)


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _endpoint_bucket(path: str) -> str:
    """Group per-file paths so stats don't explode."""
    if path.startswith("/api/ce-ota/payloads/"):
        return "/api/ce-ota/payloads/*"
    if path.startswith("/api/ce-ota/manifests/"):
        return "/api/ce-ota/manifests/*"
    return path


class Metrics:
    """In-memory request metrics; reset on restart. /health and /api/stats."""
    def __init__(self):
        self.started = time.time()
        self.requests_total = 0
        self.by_endpoint = defaultdict(int)
        self.status_codes = defaultdict(int)
        self.errors = 0
        self.clients = {}                    # ip -> {count, last_seen, build, checks, downloads}
        self.recent = deque(maxlen=100)      # most-recent-first

    def record(self, method: str, path: str, ip: str, status: int, build: Optional[str]):
        self.requests_total += 1
        self.by_endpoint[_endpoint_bucket(path)] += 1
        self.status_codes[str(status)] += 1
        if status >= 500:
            self.errors += 1
        c = self.clients.setdefault(ip, {"count": 0, "last_seen": 0.0, "build": None,
                                         "checks": 0, "downloads": 0})
        c["count"] += 1
        c["last_seen"] = time.time()
        if build:
            c["build"] = build
        if path.startswith("/api/ce-ota/check"):
            c["checks"] += 1
        if path.startswith("/api/ce-ota/payloads/"):
            c["downloads"] += 1
        self.recent.appendleft({
            "t": int(time.time()), "method": method, "path": path,
            "ip": ip, "status": status,
        })


metrics = Metrics()


@app.middleware("http")
async def access_log_and_metrics(request: Request, call_next):
    """Log every request with its build and feed the metrics."""
    ip = get_client_ip(request)
    build = request.query_params.get("build")
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception:
        metrics.record(request.method, request.url.path, ip, 500, build)
        logger.exception(f"{ip} {request.method} {request.url.path} -> 500 (unhandled)")
        raise
    metrics.record(request.method, request.url.path, ip, status, build)
    logger.info(f"ACCESS {ip} {request.method} {request.url.path} -> {status}"
                + (f" [{build}]" if build else ""))
    return response


@app.get("/")
async def root():
    return {"name": "webOS CE update server", "version": app.version, "status": "running"}


@app.get("/health")
async def health():
    """Liveness + at-a-glance health for uptime monitors."""
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - metrics.started),
        "version": app.version,
        "public_url": config.SERVER_URL,
        "requests_total": metrics.requests_total,
        "unique_clients": len(metrics.clients),
        "errors": metrics.errors,
    }


@app.get("/api/stats")
async def stats():
    """Traffic, per-device activity, recent requests."""
    now = time.time()
    clients = [
        {
            "ip": ip,
            "build": c["build"],
            "requests": c["count"],
            "checks": c["checks"],
            "downloads": c["downloads"],
            "last_seen_seconds_ago": int(now - c["last_seen"]),
        }
        for ip, c in sorted(metrics.clients.items(), key=lambda kv: -kv[1]["last_seen"])
    ]
    return {
        "uptime_seconds": int(now - metrics.started),
        "requests_total": metrics.requests_total,
        "errors": metrics.errors,
        "by_endpoint": dict(metrics.by_endpoint),
        "status_codes": dict(metrics.status_codes),
        "unique_clients": len(clients),
        "clients": clients,
        "recent": list(metrics.recent)[:30],
    }


if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        reload=config.DEBUG,
        log_level="debug" if config.DEBUG else "info",
    )
