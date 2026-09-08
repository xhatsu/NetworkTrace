"""Safe WS-Security UsernameToken identity extraction.

Only the bounded, normalized username is returned.  SOAP bodies and all other
UsernameToken material (passwords, digests, nonces, and timestamps) are ignored.
"""
from __future__ import annotations

import unicodedata
import xml.etree.ElementTree as ET
from typing import Any, Optional


WSSE_NAMESPACES = frozenset({
    "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd",
    "http://schemas.xmlsoap.org/ws/2002/07/secext",
    "http://schemas.xmlsoap.org/ws/2002/12/secext",
    "http://schemas.xmlsoap.org/ws/2003/06/secext",
})

WSSE_USERNAME_ATTRIBUTES = (
    "wsse.username",
    "wsse_username",
    "security.wsse.username",
    "http.request.wsse.username",
    "labels.wsse_username",
)

SOAP_BODY_ATTRIBUTES = (
    "http.request.body",
    "http.request.body.content",
    "labels.http_request_body",
    "request_body",
    "req_body",
    "soap_body",
    "body",
)

_MAX_SOAP_BYTES = 64 * 1024
_MAX_USERNAME_CHARS = 200


def normalize_wsse_username(value: Any) -> Optional[str]:
    """Return a storage-safe username, or None for invalid input."""
    if isinstance(value, list):
        value = value[0] if len(value) == 1 else None
    if not isinstance(value, str):
        return None
    username = value.strip()
    if not username or len(username) > _MAX_USERNAME_CHARS:
        return None
    if any(unicodedata.category(char).startswith("C") for char in username):
        return None
    return username


def extract_wsse_username(soap_body: Any) -> Optional[str]:
    """Extract a Username child from a recognized, namespaced UsernameToken."""
    if isinstance(soap_body, list):
        soap_body = soap_body[0] if len(soap_body) == 1 else None
    if isinstance(soap_body, bytes):
        raw = soap_body
    elif isinstance(soap_body, str):
        try:
            raw = soap_body.encode("utf-8")
        except UnicodeEncodeError:
            return None
    else:
        return None

    if not raw or len(raw) > _MAX_SOAP_BYTES or b"\x00" in raw:
        return None
    lowered = raw.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        return None

    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, ValueError):
        return None

    for token in root.iter():
        if not isinstance(token.tag, str) or not token.tag.startswith("{"):
            continue
        namespace, separator, local_name = token.tag[1:].partition("}")
        if not separator or namespace not in WSSE_NAMESPACES or local_name != "UsernameToken":
            continue
        username_tag = f"{{{namespace}}}Username"
        for child in token:
            if child.tag != username_tag or len(child):
                continue
            username = normalize_wsse_username(child.text)
            if username:
                return username
    return None
