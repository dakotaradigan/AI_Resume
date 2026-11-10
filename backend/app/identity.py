"""Visitor identity and client-IP resolution.

Quotas and unlock are keyed to a server-minted HttpOnly cookie (the visitor
id), never the client-supplied session id — clearing localStorage must not
reset limits, and session ids must not act as bearer tokens for entitlements
(SEC-01 in the security assessment). Conversation history is stored under
the visitor id as well (chat_service.visitor_session_key), so a session id
is not a bearer token for someone else's conversation either.

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
    """The client address every rate limit and per-IP cap keys on.

    Behind a proxy the socket peer is the proxy, so with TRUST_PROXY_HEADERS
    on the address is read from CLIENT_IP_HEADER. That header must be one the
    proxy sets itself and replaces when a caller sends its own; a header the
    caller controls would let it pick a new address, and a new bucket, on
    every request. Which header that is depends on the platform: GET
    /admin/client-ip shows what arrives. Anything missing or malformed falls
    back to the socket peer, a shared bucket, which fails closed.
    """
    peer = request.client.host if request.client else "unknown"
    if not settings.trust_proxy_headers:
        return peer
    value = request.headers.get(settings.client_ip_header, "")
    # X-Forwarded-For is a list that each proxy appends to. Only its
    # right-most entry was written by the proxy in front of us; the entries
    # to its left are the caller's to invent. Any other header is one address.
    entries = value.split(",") if settings.client_ip_header == "x-forwarded-for" else [value]
    for entry in reversed(entries):
        entry = entry.strip()
        if not entry:
            continue
        try:
            return str(ip_address(entry))
        except ValueError:
            break
    return peer


def is_loopback_host(host: str) -> bool:
    """Return True for local development hosts only."""
    if host in {"localhost", "testserver"}:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False
