#!/usr/bin/env python3
"""
anomalies.py — Modular Anomaly & User Behavior Change Generator.

Defines ground-truth anomaly scenarios aligned with TraceScope's:
1. Core Observability Detectors (Milestones 1-8):
   - Traffic Spike (Detector 1: traffic_spike)
   - Traffic Drop (Detector 2: traffic_drop)
   - Tail Latency Blowout (Detector 3: latency)
   - Cascading Failure / Error Surge (Detector 4: error_rate)
   - Architectural Drift / Rogue Dependency (Detector 5: new_service_edge)
   - Rogue Principal Access (Detector 6: new_principal_edge)
   - Novel Operation Endpoint (Detector 7: new_operation)
   - Off-Hours / Unusual Time Activity (Detector 8: unusual_time)

2. User Intelligence Behavioral Engine (principal_relationships.py & README.md):
   - Identity First Seen (USERNAME_FIRST_SEEN, score: 10)
   - Caller Expansion / New Caller (NEW_CALLER, score: 30)
   - Novel Source IP / IP Expansion (NEW_SOURCE_IP, score: 20)
   - Target Service Expansion (NEW_TARGET, score: 25)
   - Operation Expansion / New Op (NEW_OPERATION, score: 15)
   - Novel Relationship Quadruplet (NEW_RELATIONSHIP, score: 15)
   - Dormant Account Reactivation (DORMANT_REACTIVATED, score: 40)
   - Unusual Time of Day (UNUSUAL_TIME, score: 10)
   - Credential Abuse & Location Drift (credential_abuse)
"""

from __future__ import annotations
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class AnomalyContext:
    """Contextual information for evaluating and injecting anomalies and behavior changes."""
    progress: float           # 0.0 to 1.0 through the generation window
    trace_time_sec: int       # Unix timestamp in seconds
    hour_of_day: int          # 0 to 23 UTC
    window_start_sec: int     # Start of the entire generation timespan
    window_end_sec: int       # End of the entire generation timespan
    total_duration_sec: int   # Total duration in seconds (e.g. 86400 for 24h)
    bootstrap_cutoff_hour: float = 18.0  # 75% historical bootstrap cutoff in hours (default: 18h for 24h window)


class BaseScenario(ABC):
    """Abstract base class for all anomaly and user behavior change scenarios."""

    def __init__(
        self,
        name: str,
        category: str,
        description: str,
        start_hour: float,
        end_hour: float,
        enabled: bool = True,
        windows: Optional[List[Tuple[float, float]]] = None
    ):
        self.name = name
        self.category = category  # 'observability', 'user_intelligence', 'traffic', 'latency', 'security'
        self.description = description
        self.start_hour = start_hour  # Relative hour from window start [0.0 .. total_hours]
        self.end_hour = end_hour      # Relative hour from window start [0.0 .. total_hours]
        self.enabled = enabled
        self.windows = windows        # Optional list of (start_hour, end_hour) tuples for recurring incidents
        self.injection_count = 0

    def is_active(self, ctx: AnomalyContext) -> bool:
        if not self.enabled:
            return False
        elapsed_hours = (ctx.trace_time_sec - ctx.window_start_sec) / 3600.0
        if self.windows:
            return any(s <= elapsed_hours <= e for s, e in self.windows)
        return self.start_hour <= elapsed_hours <= self.end_hour

    @abstractmethod
    def mutate_transaction(
        self,
        tx: Dict[str, Any],
        ctx: AnomalyContext
    ) -> bool:
        pass


# ==============================================================================
# 1. CORE OBSERVABILITY DETECTOR SCENARIOS
# ==============================================================================

class TrafficSpikeScenario(BaseScenario):
    """Surge in transaction volume (Detector 1: traffic_spike)."""
    def __init__(
        self,
        target_service: str = "apex-order-service",
        multiplier: float = 3.5,
        start_hour: float = 10.0,
        end_hour: float = 11.5,
        enabled: bool = True
    ):
        super().__init__(
            name="traffic_spike",
            category="traffic",
            description=f"Surge in transaction volume ({multiplier}x) on {target_service}",
            start_hour=start_hour,
            end_hour=end_hour,
            enabled=enabled
        )
        self.target_service = target_service
        self.multiplier = multiplier

    def is_service_boosted(self, service_name: str, ctx: AnomalyContext) -> float:
        if self.is_active(ctx) and service_name == self.target_service:
            return self.multiplier
        return 1.0

    def mutate_transaction(self, tx: Dict[str, Any], ctx: AnomalyContext) -> bool:
        if not self.is_active(ctx):
            return False
        if tx.get("service_name") == self.target_service:
            self.injection_count += 1
            return True
        return False


class UserRateSurgeScenario(BaseScenario):
    """Sudden surge in transaction volume for a specific authenticated principal (PRINCIPAL_RATE_SURGE)."""
    def __init__(
        self,
        principal_name: str = "sale",
        multiplier: float = 3.2,
        start_hour: float = 19.0,
        end_hour: float = 20.2,
        enabled: bool = True,
        windows: Optional[List[Tuple[float, float]]] = None
    ):
        super().__init__(
            name=f"user_rate_surge_{principal_name}",
            category="user_intelligence",
            description=f"Transaction rate surge ({multiplier}x) for principal {principal_name}",
            start_hour=start_hour,
            end_hour=end_hour,
            enabled=enabled,
            windows=windows
        )
        self.principal_name = principal_name
        self.multiplier = multiplier

    def is_principal_boosted(self, p_name: str, ctx: AnomalyContext) -> float:
        if self.is_active(ctx) and p_name == self.principal_name:
            return self.multiplier
        return 1.0

    def mutate_transaction(self, tx: Dict[str, Any], ctx: AnomalyContext) -> bool:
        if not self.is_active(ctx):
            return False
        if tx.get("principal_name") == self.principal_name:
            self.injection_count += 1
            return True
        return False


class TrafficDropScenario(BaseScenario):
    """Collapse in request volume (Detector 2: traffic_drop)."""
    def __init__(
        self,
        target_service: str = "apex-notification-service",
        drop_rate: float = 0.85,
        start_hour: float = 15.5,
        end_hour: float = 16.5,
        enabled: bool = True
    ):
        super().__init__(
            name="traffic_drop",
            category="traffic",
            description=f"Traffic collapse ({int(drop_rate*100)}% drop) on {target_service}",
            start_hour=start_hour,
            end_hour=end_hour,
            enabled=enabled
        )
        self.target_service = target_service
        self.drop_rate = drop_rate

    def should_suppress_transaction(self, service_name: str, ctx: AnomalyContext) -> bool:
        if self.is_active(ctx) and service_name == self.target_service:
            if random.random() < self.drop_rate:
                self.injection_count += 1
                return True
        return False

    def mutate_transaction(self, tx: Dict[str, Any], ctx: AnomalyContext) -> bool:
        return False


class TailLatencyBlowoutScenario(BaseScenario):
    """p95 Tail latency regression (Detector 3: latency)."""
    def __init__(
        self,
        target_service: str = "apex-payment-service",
        target_operation: str = "PayService/chargeCard",
        latency_multiplier: float = 8.0,
        start_hour: float = 13.0,
        end_hour: float = 14.5,
        enabled: bool = True
    ):
        super().__init__(
            name="latency_blowout",
            category="latency",
            description=f"Tail latency blowout ({latency_multiplier}x) on {target_service} ({target_operation})",
            start_hour=start_hour,
            end_hour=end_hour,
            enabled=enabled
        )
        self.target_service = target_service
        self.target_operation = target_operation
        self.latency_multiplier = latency_multiplier

    def mutate_transaction(self, tx: Dict[str, Any], ctx: AnomalyContext) -> bool:
        if not self.is_active(ctx):
            return False
        if tx.get("service_name") == self.target_service:
            op_name = tx.get("op_name", "")
            if not self.target_operation or self.target_operation in op_name:
                base_us = tx.get("duration_us", 200000)
                inflated_us = int(base_us * self.latency_multiplier + random.randint(800000, 2500000))
                tx["duration_us"] = inflated_us
                self.injection_count += 1
                return True
        return False


class CascadingFailureScenario(BaseScenario):
    """Cascading 5xx Outage (Detector 4: error_rate)."""
    def __init__(
        self,
        root_service: str = "apex-billing-service",
        error_probability: float = 0.75,
        start_hour: float = 19.0,
        end_hour: float = 20.5,
        enabled: bool = True
    ):
        super().__init__(
            name="cascading_failure",
            category="error_rate",
            description=f"Cascading 5xx failure rooted in {root_service} propagating 502s to callers",
            start_hour=start_hour,
            end_hour=end_hour,
            enabled=enabled
        )
        self.root_service = root_service
        self.error_probability = error_probability

    def mutate_transaction(self, tx: Dict[str, Any], ctx: AnomalyContext) -> bool:
        if not self.is_active(ctx):
            return False
        svc = tx.get("service_name", "")
        caller = tx.get("caller_service", "")
        if svc == self.root_service and random.random() < self.error_probability:
            tx["status_code"] = random.choice([500, 503])
            tx["outcome"] = "failure"
            tx["result"] = "HTTP 5xx"
            self.injection_count += 1
            return True
        elif caller == self.root_service or (svc == "apex-payment-service" and random.random() < 0.35):
            tx["status_code"] = 502
            tx["outcome"] = "failure"
            tx["result"] = "HTTP 5xx"
            self.injection_count += 1
            return True
        return False


class ArchitecturalDriftScenario(BaseScenario):
    """Architectural drift: rogue caller->target edge (Detector 5: new_service_edge)."""
    def __init__(
        self,
        caller_service: str = "apex-customer-service",
        target_service: str = "apex-payment-service",
        start_hour: float = 15.0,
        end_hour: float = 24.0,
        injection_prob: float = 0.25,
        enabled: bool = True
    ):
        super().__init__(
            name="new_service_edge",
            category="topology",
            description=f"Architectural drift: rogue dependency {caller_service} -> {target_service}",
            start_hour=start_hour,
            end_hour=end_hour,
            enabled=enabled
        )
        self.caller_service = caller_service
        self.target_service = target_service
        self.injection_prob = injection_prob

    def mutate_transaction(self, tx: Dict[str, Any], ctx: AnomalyContext) -> bool:
        if not self.is_active(ctx):
            return False
        if tx.get("service_name") == self.target_service and random.random() < self.injection_prob:
            tx["caller_service"] = self.caller_service
            self.injection_count += 1
            return True
        return False


class NovelOperationScenario(BaseScenario):
    """Novel unseen endpoint deployed on service (Detector 7: new_operation)."""
    def __init__(
        self,
        target_service: str = "apex-admin-service",
        novel_path: str = "/api/v2/admin/debugDump",
        novel_op_name: str = "AdminService/debugDump",
        start_hour: float = 16.0,
        end_hour: float = 24.0,
        injection_prob: float = 0.35,
        enabled: bool = True
    ):
        super().__init__(
            name="new_operation",
            category="novelty",
            description=f"Novel unseen endpoint {novel_op_name} deployed on {target_service}",
            start_hour=start_hour,
            end_hour=end_hour,
            enabled=enabled
        )
        self.target_service = target_service
        self.novel_path = novel_path
        self.novel_op_name = novel_op_name
        self.injection_prob = injection_prob

    def mutate_transaction(self, tx: Dict[str, Any], ctx: AnomalyContext) -> bool:
        if not self.is_active(ctx):
            return False
        if tx.get("service_name") == self.target_service and random.random() < self.injection_prob:
            tx["path"] = self.novel_path
            tx["url"] = self.novel_path
            tx["route"] = "/api/v2/admin/*"
            tx["op_name"] = self.novel_op_name
            self.injection_count += 1
            return True
        return False


# ==============================================================================
# 2. USER INTELLIGENCE BEHAVIOR CHANGE SCENARIOS
# ==============================================================================

class UserFirstSeenScenario(BaseScenario):
    """
    Brand new identity appearing after 75% baseline cutoff (User Intelligence: USERNAME_FIRST_SEEN).
    Guarantees 0 observations in baseline (hours 0..18), then bursts with activity in hours 18.5..24.
    """
    def __init__(
        self,
        new_principal: str = "guest_checkout_partner",
        auth_header: str = "Basic Z3Vlc3RfY2hlY2tvdXRfcGFydG5lcjpndWVzdF9zZWNyZXRfMTAx",
        start_hour: float = 18.5,
        end_hour: float = 24.0,
        injection_prob: float = 0.20,
        enabled: bool = True
    ):
        super().__init__(
            name="user_first_seen",
            category="user_intelligence",
            description=f"New identity '{new_principal}' first observed after historical baseline cutoff",
            start_hour=start_hour,
            end_hour=end_hour,
            enabled=enabled
        )
        self.new_principal = new_principal
        self.auth_header = auth_header
        self.injection_prob = injection_prob

    def is_suppressed_in_baseline(self, principal_name: str, ctx: AnomalyContext) -> bool:
        elapsed_hours = (ctx.trace_time_sec - ctx.window_start_sec) / 3600.0
        if principal_name == self.new_principal and elapsed_hours < self.start_hour:
            return True
        return False

    def mutate_transaction(self, tx: Dict[str, Any], ctx: AnomalyContext) -> bool:
        if not self.is_active(ctx):
            return False
        if random.random() < self.injection_prob:
            tx["principal_name"] = self.new_principal
            tx["auth_header"] = self.auth_header
            self.injection_count += 1
            return True
        return False


class UserNewCallerScenario(BaseScenario):
    """
    Established principal arriving via an unexpected caller service (User Intelligence: NEW_CALLER).
    In baseline, identity only arrives from apex-edge-gateway; in hours 18.5..24 it arrives via apex-inventory-service.
    """
    def __init__(
        self,
        principal: str = "vtp",
        novel_caller: str = "apex-inventory-service",
        start_hour: float = 18.5,
        end_hour: float = 24.0,
        injection_prob: float = 0.45,
        enabled: bool = True
    ):
        super().__init__(
            name="user_new_caller",
            category="user_intelligence",
            description=f"Caller expansion: '{principal}' arriving from unexpected caller '{novel_caller}'",
            start_hour=start_hour,
            end_hour=end_hour,
            enabled=enabled
        )
        self.principal = principal
        self.novel_caller = novel_caller
        self.injection_prob = injection_prob

    def mutate_transaction(self, tx: Dict[str, Any], ctx: AnomalyContext) -> bool:
        if not self.is_active(ctx):
            return False
        if tx.get("principal_name") == self.principal and random.random() < self.injection_prob:
            tx["caller_service"] = self.novel_caller
            self.injection_count += 1
            return True
        return False


class UserNewSourceIpScenario(BaseScenario):
    """
    Established principal connecting from a foreign / unrecorded IP subnet (User Intelligence: NEW_SOURCE_IP).
    In baseline, 'sale' connects only from internal LAN; in hours 19.0..24 it connects from 185.220.101.5.
    """
    def __init__(
        self,
        principal: str = "sale",
        novel_ip: str = "185.220.101.5",
        start_hour: float = 19.0,
        end_hour: float = 24.0,
        injection_prob: float = 0.50,
        enabled: bool = True
    ):
        super().__init__(
            name="user_new_source_ip",
            category="user_intelligence",
            description=f"Source IP expansion: '{principal}' connecting from anomalous foreign IP {novel_ip}",
            start_hour=start_hour,
            end_hour=end_hour,
            enabled=enabled
        )
        self.principal = principal
        self.novel_ip = novel_ip
        self.injection_prob = injection_prob

    def mutate_transaction(self, tx: Dict[str, Any], ctx: AnomalyContext) -> bool:
        if not self.is_active(ctx):
            return False
        if tx.get("principal_name") == self.principal and random.random() < self.injection_prob:
            tx["client_ip"] = self.novel_ip
            self.injection_count += 1
            return True
        return False


class UserNewTargetScenario(BaseScenario):
    """
    Principal accessing a sensitive target service for the first time (User Intelligence: NEW_TARGET & Detector 6: new_principal_edge).
    In baseline, 'chatbot' only calls customer/catalog; in hours 18.0..23.5 it invokes apex-admin-service.
    """
    def __init__(
        self,
        principal: str = "chatbot",
        sensitive_target: str = "apex-admin-service",
        start_hour: float = 18.0,
        end_hour: float = 23.5,
        injection_prob: float = 0.35,
        enabled: bool = True
    ):
        super().__init__(
            name="user_new_target",
            category="user_intelligence",
            description=f"Target expansion: '{principal}' accessing sensitive target '{sensitive_target}'",
            start_hour=start_hour,
            end_hour=end_hour,
            enabled=enabled
        )
        self.principal = principal
        self.sensitive_target = sensitive_target
        self.injection_prob = injection_prob

    def mutate_transaction(self, tx: Dict[str, Any], ctx: AnomalyContext) -> bool:
        if not self.is_active(ctx):
            return False
        if tx.get("service_name") == self.sensitive_target and random.random() < self.injection_prob:
            tx["principal_name"] = self.principal
            tx["auth_header"] = "Basic Y2hhdGJvdDpjaGF0Ym90X2NvbnZlcnNhdGlvbl9rZXk="
            self.injection_count += 1
            return True
        return False


class UserNewOperationScenario(BaseScenario):
    """
    Principal executing an operation never observed in its baseline (User Intelligence: NEW_OPERATION).
    In baseline, 'pm_mini_app' only reads items/packages; in hours 18.5..24 it executes OrderService/cancelReservation.
    """
    def __init__(
        self,
        principal: str = "pm_mini_app",
        target_service: str = "apex-order-service",
        novel_operation: str = "OrderService/cancelReservation",
        novel_path: str = "/api/v2/orders/cancelReservation",
        start_hour: float = 18.5,
        end_hour: float = 24.0,
        injection_prob: float = 0.40,
        enabled: bool = True
    ):
        super().__init__(
            name="user_new_operation",
            category="user_intelligence",
            description=f"Operation expansion: '{principal}' executing novel operation '{novel_operation}'",
            start_hour=start_hour,
            end_hour=end_hour,
            enabled=enabled
        )
        self.principal = principal
        self.target_service = target_service
        self.novel_operation = novel_operation
        self.novel_path = novel_path
        self.injection_prob = injection_prob

    def mutate_transaction(self, tx: Dict[str, Any], ctx: AnomalyContext) -> bool:
        if not self.is_active(ctx):
            return False
        if tx.get("service_name") == self.target_service and random.random() < self.injection_prob:
            tx["principal_name"] = self.principal
            tx["auth_header"] = "Basic cG1fbWluaV9hcHA6bWluaV9hcHBfc2VjcmV0XzEyMw=="
            tx["op_name"] = self.novel_operation
            tx["path"] = self.novel_path
            tx["url"] = self.novel_path
            self.injection_count += 1
            return True
        return False


class UserUnusualTimeScenario(BaseScenario):
    """
    Off-hours activity by interactive accounts (User Intelligence: UNUSUAL_TIME & Detector 8: unusual_time).
    Human interactive identities ('sale', 'support_agent_tier3') active at 02:00-04:30 UTC.
    """
    def __init__(
        self,
        principal: str = "sale",
        start_hour: float = 2.0,
        end_hour: float = 4.5,
        injection_prob: float = 0.40,
        enabled: bool = True
    ):
        super().__init__(
            name="user_unusual_time",
            category="user_intelligence",
            description=f"Unusual time of day: off-hours access by human identity '{principal}' (02:00-04:30 UTC)",
            start_hour=start_hour,
            end_hour=end_hour,
            enabled=enabled
        )
        self.principal = principal
        self.injection_prob = injection_prob

    def is_active(self, ctx: AnomalyContext) -> bool:
        if not self.enabled:
            return False
        elapsed_hours = (ctx.trace_time_sec - ctx.window_start_sec) / 3600.0
        # In multi-day runs, keep baseline clean of off-hours interactive access
        if elapsed_hours < ctx.bootstrap_cutoff_hour:
            return False
        return 2 <= ctx.hour_of_day <= 4

    def mutate_transaction(self, tx: Dict[str, Any], ctx: AnomalyContext) -> bool:
        if not self.is_active(ctx):
            return False
        if random.random() < self.injection_prob:
            tx["principal_name"] = self.principal
            tx["auth_header"] = "Basic c2FsZTp2dF9zYWxlX3Bhc3N3b3JkXzk5"
            self.injection_count += 1
            return True
        return False


class UserDormantReactivatedScenario(BaseScenario):
    """
    Dormant account reactivation (User Intelligence: DORMANT_REACTIVATED).
    Account 'cm2.0' appears briefly in hour 0, goes completely dormant for 19 hours, then bursts at 20.0h..23.5h.
    """
    def __init__(
        self,
        principal: str = "cm2.0",
        initial_burst_hour: float = 0.5,
        reactivation_hour: float = 20.0,
        end_hour: float = 23.5,
        burst_prob: float = 0.45,
        enabled: bool = True
    ):
        super().__init__(
            name="user_dormant_reactivation",
            category="user_intelligence",
            description=f"Dormant account '{principal}' silent for 19 hours suddenly bursts with renewed activity",
            start_hour=reactivation_hour,
            end_hour=end_hour,
            enabled=enabled
        )
        self.principal = principal
        self.initial_burst_hour = initial_burst_hour
        self.reactivation_hour = reactivation_hour
        self.burst_prob = burst_prob

    def is_suppressed_in_baseline(self, principal_name: str, ctx: AnomalyContext) -> bool:
        """Allow initial appearance in early baseline (first 30 mins), then silence until reactivation hour."""
        elapsed_hours = (ctx.trace_time_sec - ctx.window_start_sec) / 3600.0
        if principal_name == self.principal:
            if self.initial_burst_hour < elapsed_hours < self.reactivation_hour:
                return True
        return False

    def mutate_transaction(self, tx: Dict[str, Any], ctx: AnomalyContext) -> bool:
        if not self.is_active(ctx):
            return False
        if random.random() < self.burst_prob:
            tx["principal_name"] = self.principal
            tx["auth_header"] = "Basic Y20yLjA6Y20yX3ZpZXR0ZWxfYXBpX3Rva2Vu"
            self.injection_count += 1
            return True
        return False


class UserCredentialAbuseScenario(BaseScenario):
    """
    Credential abuse & multiple dimension shifts (User Intelligence: NEW_SOURCE_IP + NEW_CALLER + NEW_RELATIONSHIP).
    Identity 'myViettel' connecting from abnormal public IP directly into an internal service.
    """
    def __init__(
        self,
        principal: str = "myViettel",
        abnormal_ip: str = "185.220.101.5",
        start_hour: float = 21.0,
        end_hour: float = 24.0,
        injection_prob: float = 0.50,
        enabled: bool = True
    ):
        super().__init__(
            name="credential_abuse",
            category="user_intelligence",
            description=f"Credential abuse: '{principal}' suddenly connecting from foreign IP {abnormal_ip}",
            start_hour=start_hour,
            end_hour=end_hour,
            enabled=enabled
        )
        self.principal = principal
        self.abnormal_ip = abnormal_ip
        self.injection_prob = injection_prob

    def mutate_transaction(self, tx: Dict[str, Any], ctx: AnomalyContext) -> bool:
        if not self.is_active(ctx):
            return False
        if tx.get("principal_name") == self.principal and random.random() < self.injection_prob:
            tx["client_ip"] = self.abnormal_ip
            tx["caller_service"] = "apex-customer-service"
            self.injection_count += 1
            return True
        return False


# ==============================================================================
# 3. ANOMALY & BEHAVIOR CHANGE MANAGER
# ==============================================================================

class AnomalyManager:
    """Coordinates and evaluates all active anomaly and user behavior change scenarios."""

    def __init__(self, scenarios: Optional[List[BaseScenario]] = None):
        self.scenarios: List[BaseScenario] = scenarios or []
        self._scenario_map: Dict[str, BaseScenario] = {s.name: s for s in self.scenarios}

    @classmethod
    def create_default(
        cls,
        enabled_names: Optional[Set[str]] = None,
        bootstrap_cutoff_hour: Optional[float] = None,
        total_hours: float = 24.0
    ) -> "AnomalyManager":
        """Builds the comprehensive manager with all 14 standard scenarios adapted to the timespan."""
        if bootstrap_cutoff_hour is None:
            bootstrap_cutoff_hour = total_hours * 0.75

        drift_span = max(1.0, total_hours - bootstrap_cutoff_hour)

        if total_hours > 48.0:
            # Multi-day timespan (e.g. 15 days = 360 hours)
            # Distribute incidents across the timeline + ensure incidents in the recent 24-48 hours
            spike_windows = [
                (total_hours * 0.25, total_hours * 0.25 + 2.0),
                (total_hours * 0.65, total_hours * 0.65 + 2.0),
                (total_hours - 12.0, total_hours - 10.0),
            ]
            drop_windows = [
                (total_hours * 0.45, total_hours * 0.45 + 1.5),
                (total_hours - 6.0, total_hours - 4.5),
            ]
            latency_windows = [
                (total_hours * 0.40, total_hours * 0.40 + 2.0),
                (total_hours - 8.0, total_hours - 6.0),
            ]
            failure_windows = [
                (total_hours * 0.60, total_hours * 0.60 + 2.0),
                (total_hours - 4.0, total_hours - 2.0),
            ]

            traffic_spike = TrafficSpikeScenario(start_hour=spike_windows[0][0], end_hour=spike_windows[-1][1])
            traffic_spike.windows = spike_windows

            traffic_drop = TrafficDropScenario(start_hour=drop_windows[0][0], end_hour=drop_windows[-1][1])
            traffic_drop.windows = drop_windows

            latency_blowout = TailLatencyBlowoutScenario(start_hour=latency_windows[0][0], end_hour=latency_windows[-1][1])
            latency_blowout.windows = latency_windows

            cascading_failure = CascadingFailureScenario(start_hour=failure_windows[0][0], end_hour=failure_windows[-1][1])
            cascading_failure.windows = failure_windows

            arch_drift = ArchitecturalDriftScenario(start_hour=max(bootstrap_cutoff_hour, total_hours - 24.0), end_hour=total_hours)
            novel_op = NovelOperationScenario(start_hour=max(bootstrap_cutoff_hour, total_hours - 20.0), end_hour=total_hours)

            surge_sale_windows = [
                (total_hours * 0.35, total_hours * 0.35 + 2.0),
                (total_hours - 10.0, total_hours - 8.5),
            ]
            surge_cm2_windows = [
                (total_hours * 0.55, total_hours * 0.55 + 2.0),
                (total_hours - 7.0, total_hours - 5.5),
            ]
            surge_vtp_windows = [
                (total_hours - 4.5, total_hours - 3.5),
            ]
            user_rate_surge_sale = UserRateSurgeScenario("sale", multiplier=3.2, start_hour=surge_sale_windows[0][0], end_hour=surge_sale_windows[-1][1], windows=surge_sale_windows)
            user_rate_surge_cm2 = UserRateSurgeScenario("cm2.0", multiplier=2.2, start_hour=surge_cm2_windows[0][0], end_hour=surge_cm2_windows[-1][1], windows=surge_cm2_windows)
            user_rate_surge_vtp = UserRateSurgeScenario("vtp", multiplier=2.5, start_hour=surge_vtp_windows[0][0], end_hour=surge_vtp_windows[-1][1], windows=surge_vtp_windows)
        elif total_hours < 24.0:
            traffic_spike = TrafficSpikeScenario(start_hour=0.40 * total_hours, end_hour=0.48 * total_hours)
            traffic_drop = TrafficDropScenario(start_hour=0.60 * total_hours, end_hour=0.66 * total_hours)
            latency_blowout = TailLatencyBlowoutScenario(start_hour=0.52 * total_hours, end_hour=0.58 * total_hours)
            cascading_failure = CascadingFailureScenario(start_hour=0.76 * total_hours, end_hour=0.84 * total_hours)
            arch_drift = ArchitecturalDriftScenario(start_hour=max(bootstrap_cutoff_hour, 0.70 * total_hours), end_hour=total_hours)
            novel_op = NovelOperationScenario(start_hour=max(bootstrap_cutoff_hour, 0.72 * total_hours), end_hour=total_hours)

            user_rate_surge_sale = UserRateSurgeScenario("sale", multiplier=3.2, start_hour=max(bootstrap_cutoff_hour, 0.78 * total_hours), end_hour=min(total_hours, 0.85 * total_hours))
            user_rate_surge_cm2 = UserRateSurgeScenario("cm2.0", multiplier=2.2, start_hour=max(bootstrap_cutoff_hour, 0.86 * total_hours), end_hour=min(total_hours, 0.92 * total_hours))
            user_rate_surge_vtp = UserRateSurgeScenario("vtp", multiplier=2.5, start_hour=max(bootstrap_cutoff_hour, 0.92 * total_hours), end_hour=min(total_hours, 0.98 * total_hours))
        else:
            traffic_spike = TrafficSpikeScenario(start_hour=10.0, end_hour=11.5)
            traffic_drop = TrafficDropScenario(start_hour=15.5, end_hour=16.5)
            latency_blowout = TailLatencyBlowoutScenario(start_hour=13.0, end_hour=14.5)
            cascading_failure = CascadingFailureScenario(start_hour=19.0, end_hour=20.5)
            arch_drift = ArchitecturalDriftScenario(start_hour=15.0, end_hour=total_hours)
            novel_op = NovelOperationScenario(start_hour=16.0, end_hour=total_hours)

            user_rate_surge_sale = UserRateSurgeScenario("sale", multiplier=3.2, start_hour=19.0, end_hour=20.2)
            user_rate_surge_cm2 = UserRateSurgeScenario("cm2.0", multiplier=2.2, start_hour=20.5, end_hour=21.8)
            user_rate_surge_vtp = UserRateSurgeScenario("vtp", multiplier=2.5, start_hour=22.0, end_hour=23.0)

        # User Intelligence Behavioral Changes
        # All start after bootstrap cutoff and remain active through total_hours
        user_first_seen = UserFirstSeenScenario(
            start_hour=bootstrap_cutoff_hour + (drift_span * 0.05),
            end_hour=total_hours
        )
        user_new_caller = UserNewCallerScenario(
            start_hour=bootstrap_cutoff_hour + (drift_span * 0.10),
            end_hour=total_hours
        )
        user_new_source_ip = UserNewSourceIpScenario(
            start_hour=bootstrap_cutoff_hour + (drift_span * 0.15),
            end_hour=total_hours
        )
        user_new_target = UserNewTargetScenario(
            start_hour=bootstrap_cutoff_hour + (drift_span * 0.05),
            end_hour=total_hours
        )
        user_new_op = UserNewOperationScenario(
            start_hour=bootstrap_cutoff_hour + (drift_span * 0.10),
            end_hour=total_hours
        )
        user_unusual_time = UserUnusualTimeScenario(
            start_hour=bootstrap_cutoff_hour,
            end_hour=total_hours
        )
        user_dormant = UserDormantReactivatedScenario(
            initial_burst_hour=min(2.0, bootstrap_cutoff_hour * 0.05),
            reactivation_hour=bootstrap_cutoff_hour + (drift_span * 0.25),
            end_hour=total_hours
        )
        user_abuse = UserCredentialAbuseScenario(
            start_hour=bootstrap_cutoff_hour + (drift_span * 0.35),
            end_hour=total_hours
        )

        scenarios: List[BaseScenario] = [
            traffic_spike,
            traffic_drop,
            latency_blowout,
            cascading_failure,
            arch_drift,
            novel_op,
            user_rate_surge_sale,
            user_rate_surge_cm2,
            user_rate_surge_vtp,
            user_first_seen,
            user_new_caller,
            user_new_source_ip,
            user_new_target,
            user_new_op,
            user_unusual_time,
            user_dormant,
            user_abuse
        ]
        if enabled_names is not None and "all" not in enabled_names:
            for s in scenarios:
                s.enabled = s.name in enabled_names
        return cls(scenarios)

    def get_scenario(self, name: str) -> Optional[BaseScenario]:
        return self._scenario_map.get(name)

    def get_service_traffic_multiplier(self, service_name: str, ctx: AnomalyContext) -> float:
        for s in self.scenarios:
            if isinstance(s, TrafficSpikeScenario):
                mult = s.is_service_boosted(service_name, ctx)
                if mult > 1.0:
                    return mult
        return 1.0

    def get_principal_traffic_multiplier(self, principal_name: str, ctx: AnomalyContext) -> float:
        mult = 1.0
        for s in self.scenarios:
            if isinstance(s, UserRateSurgeScenario):
                m = s.is_principal_boosted(principal_name, ctx)
                if m > mult:
                    mult = m
        return mult

    def should_drop_transaction(self, service_name: str, ctx: AnomalyContext) -> bool:
        for s in self.scenarios:
            if isinstance(s, TrafficDropScenario):
                if s.should_suppress_transaction(service_name, ctx):
                    return True
        return False

    def is_principal_suppressed_for_baseline(self, principal_name: str, ctx: AnomalyContext) -> bool:
        for s in self.scenarios:
            if isinstance(s, (UserFirstSeenScenario, UserDormantReactivatedScenario)):
                if s.is_suppressed_in_baseline(principal_name, ctx):
                    return True
        return False

    def apply_mutations(self, tx: Dict[str, Any], ctx: AnomalyContext) -> bool:
        mutated = False
        for s in self.scenarios:
            if s.is_active(ctx):
                if s.mutate_transaction(tx, ctx):
                    mutated = True
        return mutated

    def get_injection_summary(self) -> List[Dict[str, Any]]:
        summary = []
        for s in self.scenarios:
            win_str = (
                ", ".join(f"{w[0]:04.1f}h-{w[1]:04.1f}h" for w in s.windows)
                if getattr(s, "windows", None)
                else f"{s.start_hour:04.1f}h - {s.end_hour:04.1f}h"
            )
            summary.append({
                "name": s.name,
                "category": s.category,
                "description": s.description,
                "active_window_hours": win_str,
                "injected_count": s.injection_count,
                "enabled": s.enabled
            })
        return summary
