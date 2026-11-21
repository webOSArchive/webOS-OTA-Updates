#!/usr/bin/env python3
"""A stdlib-only stand-in for the CE OTA routes, for bench devices on the LAN.

    tools/bench-server.py [--port 8765] [--releases FILE]

Serves /api/ce-ota/check, /manifests/ and /payloads/ (with Range) from this
repo's ce-ota/ directory, using ce_ota.py's own release selection, so a bench
TouchPad exercises the same device filter as production without FastAPI or a
deploy. Point the device at it with
    echo http://<this host>:8765 > /media/internal/.otaready/server-url
--releases lets a bench run use its own device list instead of the tracked
ce-ota/releases.json.
"""
import argparse
import asyncio
import json
import os
import re
import sys
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SERVER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER))

# ce_ota imports fastapi only for its route decorators; stub them.
fa = types.ModuleType("fastapi")


class _Router:
    def get(self, *a, **k):
        return lambda f: f


fa.APIRouter = _Router
fa.HTTPException = Exception
fa.Request = fa.Response = object
fr = types.ModuleType("fastapi.responses")
fr.FileResponse = object
sys.modules.setdefault("fastapi", fa)
sys.modules.setdefault("fastapi.responses", fr)
import ce_ota  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body=b"", kind="application/json", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/ce-ota/check":
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            r = asyncio.run(ce_ota.check(q.get("build", ""), q.get("nduid", "")))
            return self.send(200, json.dumps(r).encode())
        m = re.match(r"^/api/ce-ota/manifests/([A-Za-z0-9._-]+\.json(\.sig)?)$", u.path)
        if m:
            p = ce_ota.MANIFEST_DIR / m.group(1)
            return self.send(200, p.read_bytes(), "application/octet-stream") if p.is_file() else self.send(404)
        m = re.match(r"^/api/ce-ota/payloads/([A-Za-z0-9._+-]+)$", u.path)
        if m:
            p = ce_ota.payload_dir() / m.group(1)
            if not p.is_file():
                return self.send(404)
            return self.payload(p)
        self.send(404)

    def payload(self, p):
        size = p.stat().st_size
        start, code, headers = 0, 200, {"Accept-Ranges": "bytes"}
        m = re.match(r"^bytes=(\d+)-$", self.headers.get("Range", ""))
        if m:
            start = int(m.group(1))
            if start >= size:
                return self.send(416, headers={"Content-Range": "bytes */%d" % size})
            code = 206
            headers["Content-Range"] = "bytes %d-%d/%d" % (start, size - 1, size)
        self.send_response(code)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size - start))
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        with open(p, "rb") as f:
            f.seek(start)
            while True:
                block = f.read(1 << 16)
                if not block:
                    break
                self.wfile.write(block)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--releases")
    a = ap.parse_args()
    if a.releases:
        ce_ota.RELEASES = Path(a.releases)
    print("bench CE OTA server on :%d, releases %s" % (a.port, ce_ota.RELEASES), flush=True)
    ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
