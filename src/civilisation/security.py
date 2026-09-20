"""Security helpers: escaping, input hygiene, secret scrubbing, URL policy, signed blobs, rate limits."""
from __future__ import annotations
import hashlib
import hmac
import html
import ipaddress
import os
import re
import socket
import time
from urllib.parse import urlparse

SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|sk-ant-[A-Za-z0-9_\-]{8,}|AIza[0-9A-Za-z_\-]{20,}|xai-[A-Za-z0-9]{8,}|gsk_[A-Za-z0-9]{8,}|Bearer [A-Za-z0-9._\-]{8,})")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def esc(x) -> str:
    """HTML-escape anything that goes into an unsafe_allow_html block."""
    return html.escape(str(x), quote=True)


def clean_text(x: str, limit: int) -> str:
    """Strip control characters and hard-limit length. Escaping happens at render time."""
    return CONTROL_RE.sub("", str(x or "")).strip()[:limit]


def scrub(msg: str) -> str:
    """Remove anything that looks like a credential from an error message before it is shown or logged."""
    return SECRET_RE.sub("[redacted]", str(msg))[:300]


def allow_custom_providers() -> bool:
    return os.environ.get("ALLOW_CUSTOM_PROVIDERS", "").lower() in ("1", "true", "yes")


def check_base_url(url: str) -> str:
    """Only https, only public hosts. Raises ValueError otherwise."""
    u = urlparse(url or "")
    if u.scheme != "https":
        raise ValueError("base URL must use https")
    host = (u.hostname or "").lower()
    if not host or host in ("localhost",) or host.endswith((".local", ".internal", ".railway.internal")):
        raise ValueError("that host is not allowed")
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError("host does not resolve")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError("that host resolves to a private address")
    return url


def _key() -> bytes | None:
    s = os.environ.get("APP_SECRET")
    return hashlib.sha256(("sign:" + s).encode()).digest() if s else None


def sign_blob(blob: bytes) -> bytes:
    k = _key()
    if not k:
        return blob
    return b"NHS1" + hmac.new(k, blob, hashlib.sha256).digest() + blob


def verify_blob(data: bytes) -> bytes:
    """Return the payload if the signature checks out. Unsigned blobs are accepted only when no APP_SECRET is set."""
    k = _key()
    if data[:4] == b"NHS1":
        if not k:
            raise ValueError("snapshot is signed but APP_SECRET is not set")
        sig, payload = data[4:36], data[36:]
        if not hmac.compare_digest(sig, hmac.new(k, payload, hashlib.sha256).digest()):
            raise ValueError("snapshot signature mismatch — refusing to load")
        return payload
    if k:
        raise ValueError("unsigned snapshot refused because APP_SECRET is set")
    return data


class Limiter:
    """Tiny per-key attempt limiter with lockout. Lives in process memory."""
    def __init__(self, max_attempts: int = 5, window: float = 600.0):
        self.max, self.window, self.hits = max_attempts, window, {}

    def allow(self, key: str) -> bool:
        now = time.time()
        hits = [t for t in self.hits.get(key, []) if now - t < self.window]
        self.hits[key] = hits
        return len(hits) < self.max

    def hit(self, key: str):
        self.hits.setdefault(key, []).append(time.time())

    def cooldown(self, key: str, seconds: float) -> float:
        """Seconds remaining before `key` may act again (0 = go)."""
        last = self.hits.get(key, [])
        return max(0.0, seconds - (time.time() - last[-1])) if last else 0.0
