from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from backend.app.repositories.trace_repository import TraceRepository
from backend.app.services.normalization import normalize_otel_record
from backend.app.services.wsse import extract_wsse_username
from backend.main import app
from backend.repository import SQLiteRepository


OASIS_2004 = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
LEGACY_NAMESPACES = (
    "http://schemas.xmlsoap.org/ws/2002/07/secext",
    "http://schemas.xmlsoap.org/ws/2002/12/secext",
    "http://schemas.xmlsoap.org/ws/2003/06/secext",
)


@pytest.fixture(scope="module", autouse=True)
def migrate_test_database():
    SQLiteRepository().migrate()


def soap_fixture(namespace: str, username: str = "  billing.user  ") -> str:
    return f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
 xmlns:wsse="{namespace}">
 <soap:Header><wsse:Security><wsse:UsernameToken>
  <wsse:Username>{username}</wsse:Username>
  <wsse:Password Type="PasswordDigest">never-store-password</wsse:Password>
  <wsse:Nonce>never-store-nonce</wsse:Nonce>
 </wsse:UsernameToken></wsse:Security></soap:Header>
 <soap:Body><GetAccount/></soap:Body>
</soap:Envelope>"""


def post(path: str, payload: dict) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(path, json=payload)

    return asyncio.run(send())


@pytest.mark.parametrize("namespace", (OASIS_2004, *LEGACY_NAMESPACES))
def test_wsse_namespace_variants_extract_only_normalized_username(namespace):
    assert extract_wsse_username(soap_fixture(namespace)) == "billing.user"


@pytest.mark.parametrize("body", (
    "<broken",
    "\ud800",
    "<UsernameToken><Username>plain-user</Username></UsernameToken>",
    f'<wsse:UsernameToken xmlns:wsse="{OASIS_2004}"><Username>plain-user</Username></wsse:UsernameToken>',
    f'<wsse:Username xmlns:wsse="{OASIS_2004}">orphan-user</wsse:Username>',
    f'<!DOCTYPE x [<!ENTITY leak "secret">]><wsse:UsernameToken xmlns:wsse="{OASIS_2004}"><wsse:Username>&leak;</wsse:Username></wsse:UsernameToken>',
))
def test_malformed_missing_or_unnamespaced_wsse_stays_anonymous(body):
    assert extract_wsse_username(body) is None
    trace = normalize_otel_record({
        "ts": 1788860000,
        "src": "pcap",
        "service": "soap-service",
        "path": "/soap",
        "soap_body": body,
    })
    assert trace is not None
    assert trace.principal_name == "unknown"
    assert not trace.attributes_json or "wsse" not in trace.attributes_json


def test_oldkernel_ingest_stores_wsse_identity_without_soap_secrets():
    trace_id = "a1000000000000000000000000000001"
    span_id = "b100000000000001"
    body = soap_fixture(OASIS_2004)
    payload = {
        "node": "wsse-oldkernel-test",
        "events": [{
            "ts": 1788860001,
            "src": "pcap",
            "service": "soap-service",
            "method": "POST",
            "path": "/soap/GetAccount",
            "soap_body": body,
            "traceparent": f"00-{trace_id}-{span_id}-01",
            "source_probe": "pcap-http",
        }],
    }

    response = post("/api/ingest", payload)
    assert response.status_code == 200
    assert response.json()["inserted"] == 1

    stored = TraceRepository().get_trace(trace_id)
    assert stored is not None
    span = stored["spans"][0]
    assert span["principal_name"] == "billing.user"
    assert json.loads(span["attributes_json"])["auth_scheme"] == "wsse"
    serialized = repr(stored)
    for forbidden in ("never-store-password", "never-store-nonce", "PasswordDigest", "soap:Envelope"):
        assert forbidden not in serialized


def test_native_otlp_accepts_sanitized_wsse_username_attribute():
    trace_id = "a2000000000000000000000000000002"
    span_id = "b200000000000002"
    payload = {"resourceSpans": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": "otlp-soap-service"}},
        ]},
        "scopeSpans": [{"spans": [{
            "traceId": trace_id,
            "spanId": span_id,
            "name": "SOAP Submit",
            "kind": 2,
            "startTimeUnixNano": "1788860002000000000",
            "endTimeUnixNano": "1788860002001000000",
            "attributes": [
                {"key": "wsse.username", "value": {"stringValue": "  otlp.wsse.user  "}},
                {"key": "http.response.status_code", "value": {"intValue": "200"}},
            ],
        }]}],
    }]}

    response = post("/v1/traces", payload)
    assert response.status_code == 200
    assert response.json() == {"partialSuccess": {}}

    stored = TraceRepository().get_trace(trace_id)
    assert stored is not None
    span = stored["spans"][0]
    assert span["principal_name"] == "otlp.wsse.user"
    assert json.loads(span["attributes_json"]) == {"auth_scheme": "wsse"}
    assert "wsse.username" not in repr(stored)
