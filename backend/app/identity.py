"""Visitor identity and client-IP resolution.

Quotas and unlock are keyed to a server-minted HttpOnly cookie (the visitor
id), never the client-supplied session id — clearing localStorage must not
reset limits, and session ids must not act as bearer tokens for entitlements
(SEC-01 in the security assessment).

The cookie value is ``<uuid>.<hmac>``, signed with SESSION_HASH_SECRET, so
only an id this server minted counts as a returning visitor. An unsigned
UUID-shaped value used to be accepted as-is, which let a client invent a new
identity (and a new quota row in the store) on every request.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from ipaddress import ip_address
from uuid import uuid4

from fastapi import Request, Response

from app.config import Settings

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
# Half of the HMAC-SHA256 digest: 128 bits is plenty for a cookie signature
# and keeps the value short.
_SIGNATURE_HEX_CHARS = 32


def _sign(visitor_id: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), visitor_id.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()[:_SIGNATURE_HEX_CHARS]


def visitor_cookie_value(visitor_id: str, settings: Settings) -> str:
    """The signed cookie form of a visitor id."""
    return f"{visitor_id}.{_sign(visitor_id, settings.session_hash_secret)}"


def resolve_visitor_id(request: Request, settings: Settings) -> tuple[str, bool]:
    """Server-owned visitor identity from the HttpOnly cookie.

    Only a UUID carrying a valid signature is accepted; anything else gets a
    fresh id. Returns (visitor_id, is_new).
    """
    raw = request.cookies.get(settings.visitor_cookie_name, "")
    visitor_id, _, signature = raw.partition(".")
    if _UUID_RE.match(visitor_id) and hmac.compare_digest(
        signature.encode("utf-8"),
        _sign(visitor_id, settings.session_hash_secret).encode("utf-8"),
    ):
        return visitor_id, False
    return str(uuid4()), True


def set_visitor_cookie(response: Response, visitor_id: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.visitor_cookie_name,
        value=visitor_cookie_value(visitor_id, settings),
        max_age=settings.visitor_ttl_seconds,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.environment == "production",
    )


def get_client_ip(request: Request, settings: Settings) -> str:
    """Best-effort client IP extraction for rate limits."""
    xff = request.headers.get("x-forwarded-for", "")
    if settings.trust_proxy_headers and xff:
        # Take the right-most IP: it was appended by the trusted proxy in front
        # of us. Left-most entries are client-supplied and trivially spoofable,
        # which would let an attacker rotate fake IPs past the rate limits.
        for forwarded_ip in reversed(xff.split(",")):
            forwarded_ip = forwarded_ip.strip()
            if not forwarded_ip:
                continue
            try:
                ip_address(forwarded_ip)
            except ValueError:
                break
            return forwarded_ip
    return request.client.host if request.client else "unknown"


def is_loopback_host(host: str) -> bool:
    """Return True for local development hosts only."""
    if host in {"localhost", "testserver"}:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False
