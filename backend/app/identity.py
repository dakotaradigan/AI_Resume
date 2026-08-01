"""Visitor identity and client-IP resolution.

Quotas and unlock are keyed to a server-minted HttpOnly cookie (the visitor
id), never the client-supplied session id — clearing localStorage must not
reset limits, and session ids must not act as bearer tokens for entitlements
(SEC-01 in the security assessment).
"""

from __future__ import annotations

import re
from ipaddress import ip_address
from uuid import uuid4

from fastapi import Request, Response

from app.config import Settings

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def resolve_visitor_id(request: Request, settings: Settings) -> tuple[str, bool]:
    """Server-owned visitor identity from the HttpOnly cookie.

    Only UUID-format cookie values are accepted. Returns (visitor_id, is_new).
    """
    raw = request.cookies.get(settings.visitor_cookie_name, "")
    if raw and _UUID_RE.match(raw):
        return raw, False
    return str(uuid4()), True


def set_visitor_cookie(response: Response, visitor_id: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.visitor_cookie_name,
        value=visitor_id,
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
