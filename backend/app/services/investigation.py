"""Single-owner, explicit-request investigator for existing findings."""
from __future__ import annotations

import asyncio
import fcntl
import functools
import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid5

from backend.config import settings
from backend.app.models.investigation import (
    AssessmentV1,
    EvidenceBundle,
    FindingRef,
    FindingSnapshot,
    InvestigationResponse,
    MAX_EVIDENCE_BYTES,
    MAX_METADATA_BYTES,
    MAX_PROMPT_BYTES,
    MAX_RESULT_BYTES,
    finding_id,
    finding_key,
)
from backend.app.repositories.investigation_evidence_repository import InvestigationEvidenceRepository
from backend.app.repositories.investigation_repository import InvestigationRepository
from backend.app.services.investigation_evidence import EvidenceAssembler, SourceError, canonical_json
from backend.app.services.investigation_provider import (
    GenerationRequest,
    LLMProvider,
    OpenAICompatibleProvider,
    ProviderFailure,
    ProviderReply,
)


log = logging.getLogger("tracescope-investigation")
POLICY_VERSION = "policy-v1"
PROMPT_VERSION = "investigation-v1"
RESULT_SCHEMA_VERSION = "assessment-v1"
QUEUE_CAPACITY = 16
TOTAL_DEADLINE_MS = 90_000
EVIDENCE_DEADLINE_MS = 15_000
PROVIDER_DEADLINE_MS = 45_000
DAY_MS = 86_400_000
TERMINAL = {"succeeded", "failed", "timed_out", "canceled", "source_changed", "source_closed", "source_superseded", "source_stale"}
NONTERMINAL = {"queued", "assembling", "generating", "validating"}


class InvestigationServiceError(RuntimeError):
    def __init__(self, code: str, message: str = "investigation request rejected", run_id: str | None = None,
                 expected_version: str | None = None, current_version: str | None = None):
        super().__init__(message)
        self.code = code
        self.run_id = run_id
        self.expected_version = expected_version
        self.current_version = current_version


def _now_ms() -> int:
    return int(time.time() * 1000)


class InvestigationRunner:
    def __init__(self, repository: InvestigationRepository | None = None,
                 evidence_repository: InvestigationEvidenceRepository | None = None,
                 provider: LLMProvider | None = None, settings_obj: Any = settings,
                 clock: Any = None):
        self.settings = settings_obj
        self.repository = repository or InvestigationRepository()
        self.evidence_repository = evidence_repository or InvestigationEvidenceRepository(settings_obj=settings_obj)
        self.provider = provider
        self.clock = clock or _now_ms
        self.assembler = EvidenceAssembler(self.evidence_repository, self.clock)
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_CAPACITY)
        self._lock = asyncio.Lock()
        self._consumer: asyncio.Task[Any] | None = None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tracescope-investigation")
        self._stop = False
        self._admissions_open = False
        self._lock_file: Any = None
        self._queue_ids: set[str] = set()
        self._active_run_id: str | None = None
        self.metrics = {"admitted": 0, "reused": 0, "failed": 0, "queue": 0}

    @property
    def available(self) -> bool:
        return bool(self._admissions_open)

    def _validate_owner_config(self) -> None:
        if not self.settings.llm_investigation_enabled:
            return
        if not self.settings.llm_single_owner_ack:
            raise InvestigationServiceError("owner_not_acknowledged", "single-owner acknowledgement is required")
        if getattr(self.settings, "storage_owner_url", ""):
            raise InvestigationServiceError("owner_proxy_forbidden", "investigation owner cannot use storage-owner proxy")
        if not self.settings.llm_model or (self.provider is None and (not self.settings.llm_base_url or not self.settings.llm_api_key)):
            raise InvestigationServiceError("provider_unconfigured", "investigation provider is not configured")
        if self.settings.llm_response_mode not in {"json_schema", "json_object"}:
            raise InvestigationServiceError("invalid_response_mode", "unsupported relay response mode")
        if int(getattr(self.settings, "llm_context_tokens", 32768)) < 32768:
            raise InvestigationServiceError("invalid_provider_context", "provider context budget is too small")

    async def _blocking(self, function: Any, *args: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, functools.partial(function, *args))

    async def start(self) -> None:
        self._validate_owner_config()
        if not self.settings.llm_investigation_enabled:
            return
        if self._consumer is not None:
            return
        try:
            Path(self.settings.data_dir).mkdir(parents=True, exist_ok=True)
            self._lock_file = open(Path(self.settings.data_dir) / "llm-investigator.lock", "a+")
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError) as exc:
            self._release_lock()
            raise InvestigationServiceError("owner_unavailable", "investigation owner is already held") from exc
        try:
            if not await self._blocking(self.repository.table_exists):
                raise InvestigationServiceError("store_schema_unavailable", "investigation table is unavailable")
            if self.provider is None:
                self.provider = OpenAICompatibleProvider(self.settings)
            self._stop = False
            self._admissions_open = False
            await self._recover()
        except ProviderFailure as exc:
            self._release_lock()
            raise InvestigationServiceError(exc.code, "investigation provider is unavailable") from exc
        except Exception:
            self._admissions_open = False
            self._release_lock()
            raise
        self._admissions_open = True
        self._consumer = asyncio.create_task(self._consume(), name="tracescope-investigation-owner")
        log.info("investigation owner started")

    def _release_lock(self) -> None:
        if self._lock_file is not None:
            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            self._lock_file.close()
            self._lock_file = None

    async def shutdown(self) -> None:
        self._admissions_open = False
        self._stop = True
        active = self._active_run_id
        consumer = self._consumer
        if consumer is not None:
            consumer.cancel()
            try:
                await consumer
            except asyncio.CancelledError:
                pass
            self._consumer = None
        ids = set(self._queue_ids)
        if active is not None:
            ids.add(active)
        try:
            rows = await self._blocking(self.repository.list_nonterminal, 100, 0)
            ids.update(str(row["id"]) for row in rows if row.get("id") is not None)
        except Exception:
            rows = []
        for run_id in ids:
            try:
                row = await self._blocking(self.repository.get, run_id, True)
                if row and row.get("state") in NONTERMINAL:
                    await self._terminal(row, "failed", "owner_interrupted")
            except Exception:
                log.warning("could not persist owner interruption run_id=%s", run_id)
        self._queue_ids.clear()
        self._active_run_id = None
        self._release_lock()
        self._executor.shutdown(wait=True, cancel_futures=True)

    async def _recover(self) -> None:
        cursor = 0
        while True:
            rows = await self._blocking(self.repository.list_nonterminal, 100, cursor)
            if not rows:
                return
            for row in rows:
                cursor = max(cursor, int(row.get("created_at_ms", 0)))
                await self._terminal(row, "failed", "owner_interrupted")
            if len(rows) < 100:
                return

    async def resolve_source(self, ref: FindingRef) -> tuple[FindingSnapshot, str, str]:
        try:
            result = await self._blocking(self.evidence_repository.load_source, ref, self.clock())
        except SourceError:
            raise
        except Exception as exc:
            raise InvestigationServiceError("store_unavailable", "finding store is unavailable") from exc
        if result is None:
            raise InvestigationServiceError("source_not_found", "finding was not found")
        return result

    async def _existing_source_run(self, ref: FindingRef, source_version: str) -> str | None:
        try:
            rows = await self._blocking(self.repository.list_for_finding, ref, 10)
        except Exception:
            return None
        for row in rows:
            if row.get("source_version") == source_version and row.get("state") in TERMINAL:
                return str(row.get("id"))
        return None

    async def _raise_source_conflict(self, ref: FindingRef, source_version: str, code: str,
                                     message: str, current_version: str | None = None) -> None:
        raise InvestigationServiceError(code, message, run_id=await self._existing_source_run(ref, source_version),
                                        expected_version=source_version, current_version=current_version)

    @staticmethod
    def eligibility_error(status: str) -> str | None:
        return {"closed": "source_closed", "stale": "source_stale", "superseded": "source_superseded",
                "insufficient_scope": "insufficient_scope", "invalid_source": "invalid_source"}.get(status)

    def _dedup_key(self, ref: FindingRef, source_version: str, retry_index: int) -> str:
        provider_name = getattr(self.provider, "name", "openai_compatible_relay")
        raw = "|".join((finding_key(ref)[0], finding_id(ref), source_version, POLICY_VERSION, PROMPT_VERSION,
                         RESULT_SCHEMA_VERSION, provider_name, self.settings.llm_model, str(retry_index)))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _run_id(dedup_key: str) -> UUID:
        return uuid5(NAMESPACE_URL, "tracescope-investigation:" + dedup_key)

    @staticmethod
    def _empty_evidence(backend: str = "none") -> str:
        return canonical_json({"schema_version": "evidence-v1", "finding_version": "0" * 64,
                               "backend": backend, "items": [], "omissions": ["not_assembled"],
                               "query_manifest": [], "calculations": [], "digest": "0" * 64})

    def _row(self, run_id: UUID, ref: FindingRef, snapshot: FindingSnapshot, dedup_key: str,
             retry_index: int, retry_of: UUID | None, now: int, deadline: int,
             summary: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": run_id, "dedup_key": dedup_key, "retry_index": retry_index, "retry_of": retry_of,
            "finding_kind": finding_key(ref)[0], "finding_id": finding_id(ref), "source_version": snapshot.source_version,
            "snapshot_schema_version": snapshot.snapshot_schema_version, "prompt_version": PROMPT_VERSION,
            "result_schema_version": RESULT_SCHEMA_VERSION, "policy_version": POLICY_VERSION,
            "provider": getattr(self.provider, "name", "openai_compatible_relay"),
            "configured_model": self.settings.llm_model, "reported_model": None, "state": "queued",
            "state_version": 1, "cancel_requested": 0, "created_at_ms": now, "updated_at_ms": now,
            "started_at_ms": None, "finished_at_ms": None, "deadline_ms": deadline,
            "expires_at": datetime.fromtimestamp((now + 30 * DAY_MS) / 1000, tz=timezone.utc),
            "snapshot_json": canonical_json(snapshot.model_dump()),
            "evidence_json": self._empty_evidence(), "evidence_digest": None,
            "deterministic_summary_json": canonical_json(summary), "result_json": None,
            "failure_code": None,
            "metadata_json": canonical_json({"requester": "api_key_operator", "attempts": [], "source_checked_at_ms": now}),
        }

    async def submit(self, ref: FindingRef, source_version: str, retry_of: UUID | None = None) -> tuple[dict[str, Any], bool, int]:
        if not self.available:
            raise InvestigationServiceError("owner_unavailable", "investigation owner is unavailable")
        snapshot, status, reason = await self.resolve_source(ref)
        if snapshot.source_version != source_version:
            await self._raise_source_conflict(ref, source_version, "source_changed", "source version no longer matches", snapshot.source_version)
        eligibility = self.eligibility_error(status)
        if eligibility:
            await self._raise_source_conflict(ref, source_version, eligibility, reason, snapshot.source_version)
        async with self._lock:
            if self._stop or not self._admissions_open:
                raise InvestigationServiceError("owner_unavailable", "investigation owner is unavailable")
            # Re-read while holding the process admission lock.  A closure or
            # version change wins over any possible deduplication reuse.
            snapshot, status, reason = await self.resolve_source(ref)
            if snapshot.source_version != source_version:
                await self._raise_source_conflict(ref, source_version, "source_changed", "source version no longer matches", snapshot.source_version)
            eligibility = self.eligibility_error(status)
            if eligibility:
                await self._raise_source_conflict(ref, source_version, eligibility, reason, snapshot.source_version)
            retry_index = 0
            if retry_of is not None:
                parent = await self._blocking(self.repository.get, retry_of, True)
                if not parent or parent.get("source_version") != source_version or parent.get("finding_kind") != finding_key(ref)[0] or parent.get("finding_id") != finding_id(ref):
                    raise InvestigationServiceError("retry_not_allowed", "retry parent is not eligible")
                if parent.get("state") not in {"failed", "timed_out", "canceled"} or int(parent.get("retry_index", 0)) >= 2:
                    raise InvestigationServiceError("retry_not_allowed", "retry parent is not eligible")
                history = await self._blocking(self.repository.list_for_finding, ref, 10)
                for previous in history:
                    if str(previous.get("id")) != str(parent.get("id")) and previous.get("source_version") == source_version and int(previous.get("retry_index", 0)) > int(parent.get("retry_index", 0)):
                        raise InvestigationServiceError("retry_not_allowed", "retry parent is not the latest terminal run")
                retry_index = int(parent.get("retry_index", 0)) + 1
            dedup_key = self._dedup_key(ref, source_version, retry_index)
            existing = await self._blocking(self.repository.get_by_dedup_key, dedup_key)
            if existing is not None:
                self.metrics["reused"] += 1
                return existing, True, 200
            if self.queue.full():
                raise InvestigationServiceError("capacity", "investigation queue is full")
            counts = await self._blocking(self.repository.admission_counts, self.clock())
            if counts["minute"] >= 6 or counts["day"] >= 100:
                raise InvestigationServiceError("rate_limited", "investigation admission rate exceeded")
            run_id = self._run_id(dedup_key)
            summary = self.assembler.deterministic_summary(snapshot, EvidenceBundle(
                finding_version=source_version, backend=getattr(self.evidence_repository, "backend", "none"),
                items=[], omissions=["not_assembled"], query_manifest=[], calculations=[], digest=hashlib.sha256(b"{}").hexdigest()))
            now = self.clock()
            row = self._row(run_id, ref, snapshot, dedup_key, retry_index, retry_of, now, now + TOTAL_DEADLINE_MS, summary)
            try:
                await self._blocking(self.repository.append_state, row)
                try:
                    self.queue.put_nowait(str(run_id))
                except asyncio.QueueFull:
                    # The reservation was checked under the same lock.  Keep
                    # the durable row explicit if a consumer raced the bound.
                    failed_row = dict(row, state="failed", state_version=2,
                                      failure_code="capacity", finished_at_ms=self.clock(),
                                      updated_at_ms=self.clock())
                    await self._blocking(self.repository.append_state, failed_row)
                    raise InvestigationServiceError("capacity", "investigation queue is full")
                self._queue_ids.add(str(run_id))
                self.metrics["admitted"] += 1
                log.info("investigation admitted run_id=%s", run_id)
            except InvestigationServiceError:
                raise
            except Exception as exc:
                raise InvestigationServiceError("store_unavailable", "investigation could not be durably queued") from exc
            return row, False, 202

    async def cancel(self, run_id: UUID) -> dict[str, Any]:
        row = await self._blocking(self.repository.get, run_id)
        if row is None:
            raise InvestigationServiceError("run_not_found", "investigation was not found")
        if row.get("state") in TERMINAL:
            return row
        if row.get("state") == "queued":
            return await self._terminal(row, "canceled", "canceled")
        return await self._transition(row, row["state"], cancel_requested=1)

    async def get(self, run_id: UUID) -> dict[str, Any] | None:
        row = await self._blocking(self.repository.get, run_id)
        if row is None:
            return None
        try:
            ref = self._ref_from_row(row)
            current = await self.resolve_source(ref)
            source_status = "current" if current[0].source_version == row["source_version"] else "changed"
            eligibility = self.eligibility_error(current[1])
            if eligibility:
                source_status = eligibility.removeprefix("source_")
            row["source_check"] = {"status": source_status, "current_version": current[0].source_version, "checked_at_ms": self.clock()}
        except InvestigationServiceError as exc:
            row["source_check"] = {"status": "missing" if exc.code == "source_not_found" else "unknown", "current_version": None, "checked_at_ms": self.clock()}
        except SourceError as exc:
            row["source_check"] = {"status": exc.code if exc.code in {"changed", "closed", "superseded", "stale"} else "unknown", "current_version": None, "checked_at_ms": self.clock()}
        if row.get("state") in NONTERMINAL and self.clock() >= int(row.get("deadline_ms", 0)):
            row["effective_status"] = "interrupted"
        for key in ("snapshot_json", "evidence_json", "deterministic_summary_json", "result_json", "metadata_json"):
            if row.get(key):
                try:
                    row[key[:-5]] = json.loads(row[key])
                except Exception:
                    row[key[:-5]] = None
        return row

    async def history(self, ref: FindingRef, limit: int = 5) -> list[dict[str, Any]]:
        rows = await self._blocking(self.repository.list_for_finding, ref, limit)
        result = []
        for row in rows:
            item = await self.get(UUID(str(row["id"])))
            if item is not None:
                result.append(item)
        return result

    @staticmethod
    def _ref_from_row(row: dict[str, Any]) -> FindingRef:
        from backend.app.models.investigation import AnomalyEventRef, IncidentRef, PrincipalChangeEventRef
        kind = row["finding_kind"]
        if kind == "anomaly_event":
            return AnomalyEventRef(kind=kind, anomaly_event_id=str(row["finding_id"]))
        if kind == "principal_change_event":
            return PrincipalChangeEventRef(kind=kind, principal_change_event_id=str(row["finding_id"]))
        if kind == "incident":
            return IncidentRef(kind=kind, incident_id=str(row["finding_id"]))
        raise SourceError("invalid_source", "stored finding kind is invalid")

    async def _consume(self) -> None:
        while not self._stop:
            run_id: str | None = None
            try:
                run_id = await self.queue.get()
                self._queue_ids.discard(run_id)
                self._active_run_id = run_id
                await self._process(UUID(run_id))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("investigation worker iteration failed")
            finally:
                self._active_run_id = None
                if run_id is not None:
                    self.queue.task_done()

    async def _source_state(self, ref: FindingRef, expected_version: str) -> tuple[FindingSnapshot, str, str] | None:
        current, status, reason = await self.resolve_source(ref)
        if current.source_version != expected_version:
            return None
        eligibility = self.eligibility_error(status)
        if eligibility:
            raise InvestigationServiceError(eligibility, reason)
        return current, status, reason

    async def _process(self, run_id: UUID) -> None:
        row = await self._blocking(self.repository.get, run_id)
        if not row or row.get("state") != "queued":
            return
        if int(row.get("cancel_requested", 0)):
            await self._terminal(row, "canceled", "canceled")
            return
        if self.clock() >= int(row["deadline_ms"]):
            await self._terminal(row, "timed_out", "queue_timeout")
            return
        ref = self._ref_from_row(row)
        try:
            source = await self._source_state(ref, row["source_version"])
            if source is None:
                await self._terminal(row, "source_changed", "source_changed")
                return
            current = source[0]
            row = await self._transition(row, "assembling", started_at_ms=self.clock())
            if row.get("state") in TERMINAL:
                return
            context = self.assembler.context(current, min(int(row["deadline_ms"]), self.clock() + EVIDENCE_DEADLINE_MS))
            remaining = max(0.001, (int(row["deadline_ms"]) - self.clock()) / 1000.0)
            bundle = await asyncio.wait_for(self._blocking(self.assembler.assemble, current, context), timeout=min(EVIDENCE_DEADLINE_MS / 1000.0, remaining))
            source_after_evidence = await self._source_state(ref, row["source_version"])
            if source_after_evidence is None:
                await self._terminal(row, "source_changed", "source_changed")
                return
            evidence_json = canonical_json(bundle.model_dump())
            if len(evidence_json.encode("utf-8")) > MAX_EVIDENCE_BYTES:
                await self._terminal(row, "failed", "evidence_budget_exceeded")
                return
            summary = self.assembler.deterministic_summary(current, bundle)
            row = await self._transition(row, "generating", evidence_json=evidence_json,
                                         evidence_digest=bundle.digest, deterministic_summary_json=canonical_json(summary))
            if row.get("state") in TERMINAL or int(row.get("cancel_requested", 0)):
                return
            prompt = self._prompt(bundle)
            if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
                await self._terminal(row, "failed", "prompt_budget_exceeded")
                return
            reply, attempts, failure_code = await self._generate(row, prompt, bundle)
            if reply is None:
                terminal = "timed_out" if failure_code in {"provider_timeout", "deadline_timeout"} else "failed"
                await self._terminal(row, terminal, failure_code or "provider_unavailable", attempts)
                return
            row = await self._transition(row, "validating", metadata=attempts, reported_model=self._safe_reported_model(reply.reported_model))
            if row.get("state") in TERMINAL:
                return
            source_before_publish = await self._source_state(ref, row["source_version"])
            if source_before_publish is None:
                await self._terminal(row, "source_changed", "source_changed")
                return
            response = self._validate_reply(reply.content, bundle)
            result_json = canonical_json(response.model_dump())
            if len(result_json.encode("utf-8")) > MAX_RESULT_BYTES:
                await self._terminal(row, "failed", "invalid_output", attempts)
                return
            if self.clock() >= int(row["deadline_ms"]):
                await self._terminal(row, "timed_out", "deadline_timeout", attempts)
                return
            await self._transition(row, "succeeded", result_json=result_json, failure_code=None,
                                   metadata=attempts, finished_at_ms=self.clock())
        except asyncio.CancelledError:
            raise
        except ProviderFailure as exc:
            await self._terminal(row, "timed_out" if exc.code == "provider_timeout" else "failed", exc.code)
        except asyncio.TimeoutError:
            await self._terminal(row, "timed_out", "deadline_timeout")
        except (SourceError, InvestigationServiceError) as exc:
            code = getattr(exc, "code", "investigation_failed")
            state = {"source_changed": "source_changed", "source_closed": "source_closed", "source_superseded": "source_superseded", "source_stale": "source_stale"}.get(code, "failed")
            await self._terminal(row, state, code)
        except Exception:
            log.exception("investigation run failed run_id=%s", run_id)
            await self._terminal(row, "failed", "worker_error")

    @staticmethod
    def _safe_reported_model(value: str | None) -> str | None:
        if not isinstance(value, str) or len(value) > 128 or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            return None
        return value

    def _prompt(self, bundle: EvidenceBundle) -> str:
        instructions = Path(__file__).resolve().parent.parent.joinpath("prompts", "investigation_v1.txt").read_text(encoding="utf-8")
        telemetry = canonical_json(bundle.model_dump())
        return instructions + "\nUNTRUSTED_TELEMETRY_DATA\n" + telemetry

    async def _generate(self, row: dict[str, Any], prompt: str, bundle: EvidenceBundle) -> tuple[ProviderReply | None, dict[str, Any], str | None]:
        if self.provider is None:
            return None, {"attempts": []}, "provider_unconfigured"
        marker = "\nUNTRUSTED_TELEMETRY_DATA\n"
        telemetry = prompt.split(marker, 1)[1] if marker in prompt else "{}"
        instructions = Path(__file__).resolve().parent.parent.joinpath("prompts", "investigation_v1.txt").read_text(encoding="utf-8")
        messages = [{"role": "system", "content": instructions}, {"role": "user", "content": "UNTRUSTED_TELEMETRY_DATA\n" + telemetry}]
        attempts: list[dict[str, Any]] = []
        deadline = min(int(row["deadline_ms"]), self.clock() + PROVIDER_DEADLINE_MS)
        request = GenerationRequest(run_id=str(row["id"]), model=self.settings.llm_model, messages=messages,
                                    max_tokens=4000, response_mode=self.settings.llm_response_mode)
        try:
            reply = await self.provider.generate(request, deadline)
            attempts.append(self._attempt_record(1, reply))
            if self.clock() >= deadline:
                return None, {"attempts": attempts}, "provider_timeout"
            try:
                self._validate_reply(reply.content, bundle)
                return reply, {"attempts": attempts}, None
            except (ValueError, TypeError):
                attempts[0]["validation"] = "schema_or_reference_error"
                if self.clock() >= deadline:
                    return None, {"attempts": attempts}, "invalid_output"
                repair = GenerationRequest(run_id=str(row["id"]), model=self.settings.llm_model,
                    messages=messages + [{"role": "user", "content": "VALIDATION_ERROR_CODES: invalid_output, unknown_reference. Return only assessment-v1 JSON with Vietnamese descriptions."}],
                    max_tokens=4000, response_mode=self.settings.llm_response_mode)
                repaired = await self.provider.generate(repair, deadline)
                attempts.append(self._attempt_record(2, repaired))
                if self.clock() >= deadline:
                    return None, {"attempts": attempts}, "provider_timeout"
                self._validate_reply(repaired.content, bundle)
                return repaired, {"attempts": attempts}, None
        except asyncio.TimeoutError:
            return None, {"attempts": attempts}, "provider_timeout"
        except ProviderFailure as exc:
            return None, {"attempts": attempts}, exc.code
        except (ValueError, TypeError, KeyError, IndexError):
            return None, {"attempts": attempts}, "invalid_output"

    @staticmethod
    def _attempt_record(number: int, reply: ProviderReply) -> dict[str, Any]:
        return {"attempt": number, "latency_ms": int(reply.latency_ms), "input_tokens": reply.input_tokens,
                "output_tokens": reply.output_tokens, "estimated_tokens": bool(reply.estimated_tokens),
                "finish_reason": reply.finish_reason}

    @staticmethod
    def _validate_reply(payload: dict[str, Any], bundle: EvidenceBundle) -> InvestigationResponse:
        assessment = AssessmentV1.model_validate(payload)
        known_evidence = {item.evidence_id for item in bundle.items}
        known_calculations = {item["calculation_id"] for item in bundle.calculations if isinstance(item, dict) and isinstance(item.get("calculation_id"), str)}
        if len(set(assessment.observed_fact_ids)) != len(assessment.observed_fact_ids) or len(set(assessment.correlation_ids)) != len(assessment.correlation_ids):
            raise ValueError("duplicate evidence or calculation reference")
        if any(value not in known_evidence for value in assessment.observed_fact_ids + [value for hypothesis in assessment.hypotheses for value in hypothesis.supporting_evidence_ids + hypothesis.counter_evidence_ids] + [value for missing in assessment.missing_evidence for value in missing.related_evidence_ids] + [value for recommendation in assessment.recommendations for value in recommendation.evidence_ids]):
            raise ValueError("unknown evidence reference")
        if any(value not in known_calculations for value in assessment.correlation_ids):
            raise ValueError("unknown calculation reference")
        if any(len(hypothesis.supporting_evidence_ids) < 1 or len(hypothesis.alternatives) < 1 for hypothesis in assessment.hypotheses):
            raise ValueError("hypothesis requires alternatives")
        facts = [{"fact_id": item.evidence_id, "kind": item.kind, "source": item.source, "data": item.data}
                 for item in bundle.items if item.evidence_id in assessment.observed_fact_ids]
        correlations = [item for item in bundle.calculations if item.get("calculation_id") in assessment.correlation_ids]
        return InvestigationResponse(schema_version="assessment-v1", assessment=assessment.assessment,
            observed_facts=facts, derived_correlations=correlations, hypotheses=assessment.hypotheses,
            missing_evidence=assessment.missing_evidence, recommendations=assessment.recommendations)

    async def _transition(self, row: dict[str, Any], state: str, **changes: Any) -> dict[str, Any]:
        async with self._lock:
            latest = await self._blocking(self.repository.get, row["id"], True)
            base = latest or row
            if base.get("state") in TERMINAL:
                return base
            if state not in NONTERMINAL | TERMINAL:
                raise InvestigationServiceError("worker_error", "invalid investigation state")
            if int(base.get("cancel_requested", 0)) and state != "canceled":
                state = "canceled"
                changes = {"failure_code": "canceled", "finished_at_ms": self.clock(), "cancel_requested": 1}
            next_row = dict(base)
            if "metadata" in changes:
                changes["metadata_json"] = canonical_json(changes.pop("metadata"))
            next_row.update(changes)
            next_row["state"] = state
            next_row["state_version"] = int(base.get("state_version", 0)) + 1
            next_row["updated_at_ms"] = self.clock()
            await self._blocking(self.repository.append_state, next_row)
            return next_row

    async def _terminal(self, row: dict[str, Any], state: str, failure_code: str,
                        metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        if row.get("state") in TERMINAL:
            return row
        safe_metadata = metadata or {}
        if not safe_metadata:
            safe_metadata = {"failure_class": failure_code}
        else:
            safe_metadata = dict(safe_metadata)
            safe_metadata["failure_class"] = failure_code
        try:
            return await self._transition(row, state, failure_code=failure_code,
                                          finished_at_ms=self.clock(), metadata=safe_metadata)
        except Exception:
            self.metrics["failed"] += 1
            raise
