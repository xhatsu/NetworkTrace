from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend.app.models.investigation import AnomalyEventRef
from backend.app.services.investigation import InvestigationRunner
from backend.app.services.investigation_evidence import build_snapshot
from backend.app.services.investigation_provider import ProviderReply


class MemoryRepo:
    def __init__(self): self.rows = {}
    def table_exists(self): return True
    def get(self, run_id, include_expired=False): return self.rows.get(str(run_id))
    def get_by_dedup_key(self, key, include_expired=False):
        return next((row for row in self.rows.values() if row["dedup_key"] == key), None)
    def admission_counts(self, now): return {"minute": 0, "day": 0, "active": 0}
    def append_state(self, row): self.rows[str(row["id"])] = dict(row)
    def list_nonterminal(self, limit, cursor): return []
    def list_for_finding(self, ref, limit): return [row for row in self.rows.values() if row["finding_id"] == ref.model_dump().get("anomaly_event_id")][:limit]


class Evidence:
    backend = "none"
    def load_source(self, ref, now):
        return build_snapshot(ref, {"id": 1, "detected_at": now, "anomaly_type": "traffic_spike", "severity": "high", "score": 2,
            "target_service": "orders", "first_seen": now - 1000, "last_seen": now, "status": "open", "reason_json": "[]", "metadata_json": "{}"}, now)
    def related_traces(self, *args): return []
    def window_metrics(self, *args): return []
    def attached_baseline(self, *args): return []
    def principal_history(self, *args): return []
    def service_context(self, *args): return []
    def data_quality(self, *args): return []


class Provider:
    name = "fake"
    calls = 0
    async def generate(self, request, deadline):
        self.calls += 1
        return ProviderReply({"schema_version": "assessment-v1", "assessment": "insufficient_evidence", "observed_fact_ids": ["source-0"], "correlation_ids": [], "hypotheses": [], "missing_evidence": [], "recommendations": []})


def test_fake_provider_flow_deduplicates():
    async def run():
        now = 1_700_000_100_000
        cfg = SimpleNamespace(llm_investigation_enabled=True, llm_single_owner_ack=True, storage_owner_url="", llm_model="fake",
                              llm_base_url="", llm_api_key="", llm_response_mode="json_object", data_dir="/tmp")
        repo, evidence, provider = MemoryRepo(), Evidence(), Provider()
        runner = InvestigationRunner(repo, evidence, provider, cfg, clock=lambda: now)
        runner._admissions_open = True
        ref = AnomalyEventRef(kind="anomaly_event", anomaly_event_id="1")
        version = evidence.load_source(ref, now)[0].source_version
        first, reused, _ = await runner.submit(ref, version)
        second, reused, _ = await runner.submit(ref, first["source_version"])
        assert str(first["id"]) == str(second["id"])
        assert reused
    asyncio.run(run())
