"""
Configuration for the webOS CE update server.
"""
import os
import socket
import configparser
from pathlib import Path

BASE_DIR = Path(__file__).parent


def _lan_ip():
    """Best-effort primary LAN IP of this host (the address devices reach us on).
    Uses a UDP socket toward the LAN gateway range — no packets are actually sent."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.10.1", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# --- Settings come from a config file (not environment variables). ---
# Searched in order; first found wins; missing file -> built-in defaults:
#   /etc/otaserver.conf      (production)
#   <repo>/otaserver.conf    (local/dev; shipped with dev defaults)
# interpolation=None so URLs containing '%' are not mangled.
_conf = configparser.ConfigParser(interpolation=None)
CONF_PATH = None
for _p in ("/etc/otaserver.conf", str(BASE_DIR / "otaserver.conf")):
    if os.path.exists(_p):
        _conf.read(_p)
        CONF_PATH = _p
        break


def _cget(section, key, default=""):
    return (_conf.get(section, key, fallback=default) or "").strip()


# Server settings
SERVER_HOST = _cget("server", "host", "0.0.0.0") or "0.0.0.0"
SERVER_PORT = int(_cget("server", "port", "8080") or "8080")
DEBUG = _cget("server", "debug", "true").lower() in ("1", "true", "yes", "on")

# Public base URL, reported by /health.
#   [public] url set   -> used verbatim
#   [public] host set  -> https://<host>            (production)
#   neither            -> http://<LAN IP>:<PORT>    (local dev, auto-detected)
PUBLIC_HOST = _cget("public", "host", "")
_server_url = _cget("public", "url", "")
if _server_url:
    SERVER_URL = _server_url
elif PUBLIC_HOST:
    SERVER_URL = f"https://{PUBLIC_HOST}"
else:
    SERVER_URL = f"http://{_lan_ip()}:{SERVER_PORT}"

# Optional persistent rotating access log; blank -> stdout/journald only.
LOG_FILE = _cget("logging", "file", "") or None

# CE OTA payloads (large, not in git). Blank -> <repo>/ce-ota/payloads.
CE_OTA_PAYLOAD_DIR = _cget("ce_ota", "payload_dir", "")
