from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping, Sequence


class RiskSeverity(StrEnum):
    INFORMATIONAL = "informational"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class ReliabilityTier(StrEnum):
    CLINICAL = "clinical"
    OS_AGGREGATOR = "os_aggregator"
    STANDARD_BLE = "standard_ble"
    VENDOR_API = "vendor_api"
    MANUAL_OR_OCR = "manual_or_ocr"
    UNKNOWN = "unknown"


class FreshnessStatus(StrEnum):
    FRESH = "fresh"
    DELAYED = "delayed"
    STALE = "stale"
    FUTURE_TIMESTAMP = "future_timestamp"
    UNKNOWN = "unknown"


SEVERITY_RANK: dict[RiskSeverity, int] = {
    RiskSeverity.INFORMATIONAL: 0,
    RiskSeverity.LOW: 1,
    RiskSeverity.MODERATE: 2,
    RiskSeverity.HIGH: 3,
    RiskSeverity.CRITICAL: 4,
}


def coerce_severity(value: str | RiskSeverity) -> RiskSeverity:
    return value if isinstance(value, RiskSeverity) else RiskSeverity(value)


def coerce_reliability(value: str | ReliabilityTier | None) -> ReliabilityTier:
    if value is None:
        return ReliabilityTier.UNKNOWN
    return value if isinstance(value, ReliabilityTier) else ReliabilityTier(value)


@dataclass(frozen=True)
class Observation:
    patient_id: str
    metric_code: str
    observed_at: datetime
    value_numeric: float | None = None
    value_text: str | None = None
    unit: str | None = None
    source_type: str | None = None
    reliability_tier: ReliabilityTier | str | None = ReliabilityTier.UNKNOWN
    confidence: float = 1.0
    ingested_at: datetime | None = None
    source_label: str | None = None
    source_record_id: str | None = None
    review_status: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def value(self) -> float | str | bool | None:
        if self.value_numeric is not None:
            return self.value_numeric
        if self.value_text is None:
            return None
        lowered = self.value_text.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        return self.value_text


@dataclass(frozen=True)
class ObservationQuality:
    freshness: FreshnessStatus
    quality_score: float
    quality_flags: tuple[str, ...]
    source_observed_age_seconds: int | None
    reliability_tier: ReliabilityTier
    reliability_score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "freshness": self.freshness.value,
            "quality_score": self.quality_score,
            "quality_flags": list(self.quality_flags),
            "source_observed_age_seconds": self.source_observed_age_seconds,
            "reliability_tier": self.reliability_tier.value,
            "reliability_score": self.reliability_score,
        }


@dataclass(frozen=True)
class RiskRule:
    rule_key: str
    version: int
    name: str
    severity: RiskSeverity | str
    metric_codes: tuple[str, ...]
    conditions: Mapping[str, Any]
    rationale: str
    required_reliability: tuple[ReliabilityTier, ...] = ()
    reviewer: str | None = None
    active: bool = True

    @property
    def severity_value(self) -> RiskSeverity:
        return coerce_severity(self.severity)

    @property
    def rule_id(self) -> str:
        return f"{self.rule_key}:v{self.version}"


@dataclass(frozen=True)
class RiskEvidence:
    metric: str
    value: float | str | bool | None
    unit: str | None
    observed_at: datetime
    source: str
    rule_key: str
    rule_version: int
    quality: ObservationQuality
    source_record_id: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "metric": self.metric,
            "value": self.value,
            "unit": self.unit,
            "observed_at": self.observed_at.isoformat(),
            "source": self.source,
            "rule_key": self.rule_key,
            "rule_version": self.rule_version,
            "quality": self.quality.as_dict(),
        }
        if self.source_record_id:
            payload["source_record_id"] = self.source_record_id
        if self.details:
            payload["details"] = dict(self.details)
        return payload


@dataclass(frozen=True)
class RiskEvaluation:
    patient_id: str
    severity: RiskSeverity
    confidence: float
    reason: str
    evidence: tuple[RiskEvidence, ...]
    rule: RiskRule
    idempotency_key: str
    recommended_action: str
    requires_policy_approval: bool = False
    requires_patient_confirmation: bool = False
    should_escalate_as_emergency: bool = False

    def as_risk_event_create_request(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "evidence": [item.as_dict() for item in self.evidence],
            "rule_id": self.rule.rule_id,
            "recommended_action": self.recommended_action,
            "idempotency_key": self.idempotency_key,
            "policy_flags": {
                "requires_policy_approval": self.requires_policy_approval,
                "requires_patient_confirmation": self.requires_patient_confirmation,
                "should_escalate_as_emergency": self.should_escalate_as_emergency,
            },
        }


def highest_severity(evaluations: Sequence[RiskEvaluation]) -> RiskSeverity:
    if not evaluations:
        return RiskSeverity.INFORMATIONAL
    return max(evaluations, key=lambda event: SEVERITY_RANK[event.severity]).severity
