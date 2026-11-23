"""CE OTA (webOS CE 3.1.0 onward): signed manifests, a device filter, payloads.

The client (OTA Ready v2's daemon, or the same daemon baked into an image) asks

    GET /api/ce-ota/check?build=<BUILDMARK>&nduid=<device id>

and gets {"status": "UpToDate"} or {"status": "Available", "manifest": "<name>"}.
It then fetches the manifest and its signature as raw bytes,

    GET /api/ce-ota/manifests/<name>.json
    GET /api/ce-ota/manifests/<name>.json.sig

verifies the signature with the key baked into the device image, and only then
believes anything in it, including the payload URL:

    GET /api/ce-ota/payloads/<file>          (Range supported, for resuming)

Who is offered what is decided here, in ce-ota/releases.json:

    {"releases": [
        {"manifest": "600070-600120", "devices": ["<nduid>", "<nduid>"]},
        {"manifest": "600070-600120", "devices": "*"}
    ]}

"devices" is "*" (every device on that build) or a list of nduids, so the same
file covers bench testing and a gradual rollout. The first release whose manifest
starts at the device's build and whose filter admits the device wins. This is
rollout policy, not security: the signature is what authorises an install, and a
device that fetches a manifest it was not offered can do nothing with it that it
could not do once the release reaches "*". Edit the file and git push; it is read
on every request.

Manifests and signatures are tracked in git (ce-ota/manifests/). Payloads are
large and are not: they live in [ce_ota] payload_dir (default ce-ota/payloads/,
git-ignored) and are copied to the host by hand.
"""
import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse

import config

logger = logging.getLogger(__name__)
router = APIRouter()

CE_OTA_DIR = config.BASE_DIR / "ce-ota"
MANIFEST_DIR = CE_OTA_DIR / "manifests"
RELEASES = CE_OTA_DIR / "releases.json"

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
NDUID_RE = re.compile(r"^[0-9a-f]{40}$")
BUILD_RE = re.compile(r"^[0-9]{1,12}$")


def payload_dir() -> Path:
    return Path(config.CE_OTA_PAYLOAD_DIR) if config.CE_OTA_PAYLOAD_DIR else CE_OTA_DIR / "payloads"


def _safe_name(name: str) -> str:
    if not NAME_RE.match(name or "") or ".." in name:
        raise HTTPException(status_code=404, detail="not found")
    return name


def _admits(devices, nduid: str) -> bool:
    if devices == "*":
        return True
    if isinstance(devices, list):
        return bool(nduid) and nduid in [str(d).strip().lower() for d in devices]
    return False


def _manifest_from(name: str):
    """The from-buildmark a manifest names, or None if it is missing or unreadable."""
    try:
        m = json.loads((MANIFEST_DIR / (name + ".json")).read_text())
        return str(m["from"]["buildmark"])
    except Exception as e:
        logger.error(f"ce-ota: manifest {name} unreadable: {e}")
        return None


def select_release(build: str, nduid: str):
    try:
        releases = json.loads(RELEASES.read_text()).get("releases", [])
    except FileNotFoundError:
        return None
    except Exception as e:
        logger.error(f"ce-ota: releases.json unreadable, offering nothing: {e}")
        return None
    for r in releases:
        name = r.get("manifest", "")
        if not NAME_RE.match(name) or not _admits(r.get("devices"), nduid):
            continue
        if _manifest_from(name) != build:
            continue
        if not (MANIFEST_DIR / (name + ".json.sig")).exists():
            logger.error(f"ce-ota: manifest {name} has no signature; not offered")
            continue
        return name
    return None


@router.get("/api/ce-ota/check")
async def check(build: str = "", nduid: str = ""):
    nduid = nduid.strip().lower()
    if not BUILD_RE.match(build):
        return {"status": "UpToDate", "reason": "no build"}
    if nduid and not NDUID_RE.match(nduid):
        nduid = ""
    name = select_release(build, nduid)
    logger.info(f"ce-ota check build={build} nduid=…{nduid[-6:] if nduid else '-'} -> {name or 'UpToDate'}")
    if not name:
        return {"status": "UpToDate"}
    return {"status": "Available", "manifest": name}


@router.get("/api/ce-ota/manifests/{filename}")
async def manifest(filename: str):
    if filename.endswith(".json.sig"):
        name, kind = filename[:-9], "application/octet-stream"
    elif filename.endswith(".json"):
        name, kind = filename[:-5], "application/json"
    else:
        raise HTTPException(status_code=404, detail="not found")
    path = MANIFEST_DIR / (_safe_name(name) + filename[len(name):])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    # Served as raw bytes: the signature covers exactly these bytes.
    return Response(content=path.read_bytes(), media_type=kind,
                    headers={"Cache-Control": "no-cache"})


def ranged_file(path: Path, request: Request):
    """A file response honouring a single 'bytes=start-[end]' Range (curl -C -)."""
    size = path.stat().st_size
    rng = request.headers.get("Range", "")
    m = re.match(r"^bytes=(\d*)-(\d*)$", rng.strip())
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
        else:                                   # suffix range: the last N bytes
            start, end = max(0, size - int(m.group(2))), size - 1
        if start >= size:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        end = min(end, size - 1)
        with open(path, "rb") as f:
            f.seek(start)
            body = f.read(end - start + 1)
        return Response(content=body, status_code=206, media_type="application/octet-stream",
                        headers={"Content-Range": f"bytes {start}-{end}/{size}",
                                 "Accept-Ranges": "bytes"})
    return FileResponse(path=path, filename=path.name, media_type="application/octet-stream",
                        headers={"Accept-Ranges": "bytes"})


@router.get("/api/ce-ota/payloads/{filename}")
async def payload(filename: str, request: Request):
    path = payload_dir() / _safe_name(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return ranged_file(path, request)
