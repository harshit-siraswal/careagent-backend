from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from app.domain.risk import (
    FreshnessStatus,
    Observation,
    ObservationQuality,
    ReliabilityTier,
    RiskEvaluation,
    RiskEvidence,
    RiskRule,
    RiskSeverity,
    SEVERITY_RANK,
    coerce_reliability,
)


RELIABILITY_SCORES: dict[ReliabilityTier, float] = {
    ReliabilityTier.CLINICAL: 0.95,
    ReliabilityTier.STANDARD_BLE: 0.9,
    ReliabilityTier.OS_AGGREGATOR: 0.82,
    ReliabilityTier.VENDOR_API: 0.78,
    ReliabilityTier.MANUAL_OR_OCR: 0.58,
    ReliabilityTier.UNKNOWN: 0.4,
}

METRIC_FRESHNESS: dict[str, tuple[timedelta, timedelta]] = {
    "heart_rate": (timedelta(minutes=5), timedelta(minutes=15)),
    "blood_pressure_systolic": (timedelta(minutes=30), timedelta(hours=2)),
    "blood_pressure_diastolic": (timedelta(minutes=30), timedelta(hours=2)),
    "blood_glucose": (timedelta(minutes=30), timedelta(hours=2)),
    "continuous_glucose": (timedelta(minutes=15), timedelta(minutes=45)),
    "spo2": (timedelta(minutes=5), timedelta(minutes=15)),
    "body_temperature": (timedelta(hours=2), timedelta(hours=8)),
    "respiratory_rate": (timedelta(minutes=15), timedelta(hours=1)),
    "fall_detected": (timedelta(seconds=0), timedelta(minutes=15)),
}

DEFAULT_RULES: tuple[RiskRule, ...] = (
    RiskRule(
        rule_key="spo2_critical_low",
        version=1,
        name="Critical low oxygen saturation",
        severity=RiskSeverity.CRITICAL,
        metric_codes=("spo2",),
        conditions={"operator": "<=", "value": 88},
        required_reliability=(ReliabilityTier.CLINICAL, ReliabilityTier.STANDARD_BLE, ReliabilityTier.OS_AGGREGATOR, ReliabilityTier.VENDOR_API),
        rationale="SpO2 at or below 88% can indicate severe hypoxemia and must be reviewed immediately.",
        reviewer="clinical-review-required",
    ),
    RiskRule(
        rule_key="spo2_low",
        version=1,
        name="Low oxygen saturation",
        severity=RiskSeverity.HIGH,
        metric_codes=("spo2",),
        conditions={"operator": "<=", "value": 92},
        rationale="SpO2 at or below 92% should prompt urgent recheck or escalation depending on patient context.",
    ),
    RiskRule(
        rule_key="blood_glucose_low",
        version=1,
        name="Low blood glucose",
        severity=RiskSeverity.HIGH,
        metric_codes=("blood_glucose", "continuous_glucose"),
        conditions={"operator": "<", "value": 70},
        rationale="Glucose below 70 mg/dL can indicate hypoglycemia.",
    ),
    RiskRule(
        rule_key="blood_glucose_critical_low",
        version=1,
        name="Critical low blood glucose",
        severity=RiskSeverity.CRITICAL,
        metric_codes=("blood_glucose", "continuous_glucose"),
        conditions={"operator": "<=", "value": 54},
        required_reliability=(ReliabilityTier.CLINICAL, ReliabilityTier.STANDARD_BLE, ReliabilityTier.OS_AGGREGATOR, ReliabilityTier.VENDOR_API),
        rationale="Glucose at or below 54 mg/dL is clinically significant hypoglycemia.",
        reviewer="clinical-review-required",
    ),
    RiskRule(
        rule_key="heart_rate_low",
        version=1,
        name="Low heart rate",
        severity=RiskSeverity.HIGH,
        metric_codes=("heart_rate",),
        conditions={"operator": "<=", "value": 45},
        rationale="Very low heart rate may require urgent attention when fresh and reliable.",
    ),
    RiskRule(
        rule_key="heart_rate_high",
        version=1,
        name="High heart rate",
        severity=RiskSeverity.HIGH,
        metric_codes=("heart_rate",),
        conditions={"operator": ">=", "value": 130},
        rationale="Very high heart rate may require urgent attention when fresh and reliable.",
    ),
    RiskRule(
        rule_key="blood_pressure_systolic_high",
        version=1,
        name="High systolic blood pressure",
        severity=RiskSeverity.HIGH,
        metric_codes=("blood_pressure_systolic",),
        conditions={"operator": ">=", "value": 180},
        rationale="Systolic pressure at or above 180 mmHg can require urgent follow-up.",
    ),
    RiskRule(
        rule_key="body_temperature_high",
        version=1,
        name="High body temperature",
        severity=RiskSeverity.MODERATE,
        metric_codes=("body_temperature",),
        conditions={"operator": ">=", "value": 39},
        rationale="High fever should trigger care-team review.",
    ),
    RiskRule(
        rule_key="fall_detected",
        version=1,
        name="Fall detected",
        severity=RiskSeverity.CRITICAL,
        metric_codes=("fall_detected",),
        conditions={"operator": "truthy"},
        required_reliability=(ReliabilityTier.STANDARD_BLE, ReliabilityTier.OS_AGGREGATOR, ReliabilityTier.VENDOR_API, ReliabilityTier.CLINICAL),
        rationale="A device-reported fall event may require immediate human verification and escalation.",
        reviewer="clinical-review-required",
    ),
)


def parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def observation_from_mapping(payload: Mapping[str, Any], patient_id: str) -> Observation:
    return Observation(
        patient_id=patient_id,
        metric_code=str(payload["metric_code"]),
        value_numeric=_to_float(payload.get("value_numeric")),
        value_text=payload.get("value_text"),
        unit=payload.get("unit"),
        observed_at=_require_datetime(payload["observed_at"]),
        ingested_at=parse_datetime(payload.get("ingested_at")),
        source_type=payload.get("source_type"),
        reliability_tier=payload.get("reliability_tier"),
        confidence=float(payload.get("confidence", 1.0)),
        source_label=payload.get("source_label"),
        source_record_id=payload.get("source_record_id"),
        review_status=payload.get("review_status"),
        metadata={key: value for key, value in payload.items() if key not in {"raw_payload"}},
    )


def evaluate_observations(
    observations: Iterable[Observation | Mapping[str, Any]],
    *,
    patient_id: str,
    now: datetime | None = None,
    rules: Sequence[RiskRule] = DEFAULT_RULES,
) -> list[RiskEvaluation]:
    clock = _ensure_aware(now or datetime.now(timezone.utc))
    normalized = [
        item if isinstance(item, Observation) else observation_from_mapping(item, patient_id)
        for item in observations
    ]
    events: list[RiskEvaluation] = []

    for observation in normalized:
        quality = assess_observation_quality(observation, now=clock)
        for rule in rules:
            if not rule.active or observation.metric_code not in rule.metric_codes:
                continue
            if not _rule_matches(rule, observation):
                continue
            event = _build_evaluation(observation, quality, rule, now=clock)
            if event is not None:
                events.append(event)

    stale_events = _evaluate_stale_observations(normalized, patient_id=patient_id, now=clock)
    events.extend(stale_events)
    return dedupe_evaluations(events)


def assess_observation_quality(observation: Observation, *, now: datetime) -> ObservationQuality:
    reliability = coerce_reliability(observation.reliability_tier)
    reliability_score = RELIABILITY_SCORES[reliability]
    observed_at = _ensure_aware(observation.observed_at)
    clock = _ensure_aware(now)
    age = clock - observed_at
    flags: list[str] = []

    if age.total_seconds() < -120:
        freshness = FreshnessStatus.FUTURE_TIMESTAMP
        flags.append("future_timestamp")
    else:
        warning_after, stale_after = METRIC_FRESHNESS.get(
            observation.metric_code,
            (timedelta(minutes=30), timedelta(hours=2)),
        )
        if age <= warning_after:
            freshness = FreshnessStatus.FRESH
        elif age <= stale_after:
            freshness = FreshnessStatus.DELAYED
            flags.append("delayed")
        else:
            freshness = FreshnessStatus.STALE
            flags.append("stale")

    if reliability == ReliabilityTier.MANUAL_OR_OCR:
        flags.append("manual_source")
        if observation.review_status and observation.review_status != "approved":
            flags.append(f"review_{observation.review_status}")
    elif reliability == ReliabilityTier.VENDOR_API:
        flags.append("vendor_event")
    elif reliability == ReliabilityTier.UNKNOWN:
        flags.append("unknown_reliability")

    quality = reliability_score * max(0.0, min(1.0, observation.confidence))
    if freshness == FreshnessStatus.DELAYED:
        quality *= 0.82
    elif freshness == FreshnessStatus.STALE:
        quality *= 0.62
    elif freshness == FreshnessStatus.FUTURE_TIMESTAMP:
        quality *= 0.25

    return ObservationQuality(
        freshness=freshness,
        quality_score=round(quality, 4),
        quality_flags=tuple(dict.fromkeys(flags)),
        source_observed_age_seconds=int(age.total_seconds()),
        reliability_tier=reliability,
        reliability_score=reliability_score,
    )


def make_risk_event_idempotency_key(
    patient_id: str,
    rule_key: str,
    rule_version: int,
    window_start: datetime,
    evidence: Sequence[Mapping[str, Any]],
) -> str:
    evidence_hash = stable_hash(evidence)[:16]
    window = _ensure_aware(window_start).replace(second=0, microsecond=0).isoformat()
    return f"risk:{patient_id}:{rule_key}:v{rule_version}:{window}:{evidence_hash}"


def make_outbox_event_key(topic: str, aggregate_id: str, patient_id: str | None = None) -> str:
    if patient_id:
        return f"{topic}:{patient_id}:{aggregate_id}"
    return f"{topic}:{aggregate_id}"


def make_escalation_idempotency_key(risk_event_id: str, policy_id: str) -> str:
    return f"escalation:{risk_event_id}:{policy_id}"


def stable_hash(payload: Any) -> str:
    canonical = json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def dedupe_evaluations(events: Sequence[RiskEvaluation]) -> list[RiskEvaluation]:
    by_key: dict[str, RiskEvaluation] = {}
    for event in events:
        existing = by_key.get(event.idempotency_key)
        if existing is None or SEVERITY_RANK[event.severity] > SEVERITY_RANK[existing.severity]:
            by_key[event.idempotency_key] = event
    return list(by_key.values())


def _build_evaluation(
    observation: Observation,
    quality: ObservationQuality,
    rule: RiskRule,
    *,
    now: datetime,
) -> RiskEvaluation | None:
    severity = _effective_severity(rule.severity_value, quality)
    if severity == RiskSeverity.INFORMATIONAL:
        return None

    source = observation.source_label or observation.source_type or quality.reliability_tier.value
    evidence = RiskEvidence(
        metric=observation.metric_code,
        value=observation.value,
        unit=observation.unit,
        observed_at=observation.observed_at,
        source=source,
        rule_key=rule.rule_key,
        rule_version=rule.version,
        quality=quality,
        source_record_id=observation.source_record_id,
        details={"rationale": rule.rationale},
    )
    evidence_dict = evidence.as_dict()
    idempotency_key = make_risk_event_idempotency_key(
        observation.patient_id,
        rule.rule_key,
        rule.version,
        observation.observed_at,
        [evidence_dict],
    )
    requires_confirmation = quality.reliability_tier == ReliabilityTier.MANUAL_OR_OCR and SEVERITY_RANK[severity] >= SEVERITY_RANK[RiskSeverity.HIGH]
    should_emergency = severity == RiskSeverity.CRITICAL and quality.freshness == FreshnessStatus.FRESH and not requires_confirmation
    reason = _reason_for(rule, observation, quality, severity)
    return RiskEvaluation(
        patient_id=observation.patient_id,
        severity=severity,
        confidence=round(min(1.0, quality.quality_score), 4),
        reason=reason,
        evidence=(evidence,),
        rule=rule,
        idempotency_key=idempotency_key,
        recommended_action=_recommended_action(severity, requires_confirmation, quality.freshness),
        requires_policy_approval=SEVERITY_RANK[severity] >= SEVERITY_RANK[RiskSeverity.HIGH],
        requires_patient_confirmation=requires_confirmation,
        should_escalate_as_emergency=should_emergency,
    )


def _evaluate_stale_observations(
    observations: Sequence[Observation],
    *,
    patient_id: str,
    now: datetime,
) -> list[RiskEvaluation]:
    events: list[RiskEvaluation] = []
    for observation in observations:
        quality = assess_observation_quality(observation, now=now)
        if quality.freshness != FreshnessStatus.STALE:
            continue
        rule = RiskRule(
            rule_key=f"{observation.metric_code}_stale",
            version=1,
            name=f"Stale {observation.metric_code} data",
            severity=RiskSeverity.LOW,
            metric_codes=(observation.metric_code,),
            conditions={"freshness": "stale"},
            rationale="Missing or stale data is a data-quality risk, not proof of normal status or live deterioration.",
        )
        evidence = RiskEvidence(
            metric=observation.metric_code,
            value=observation.value,
            unit=observation.unit,
            observed_at=observation.observed_at,
            source=observation.source_label or observation.source_type or quality.reliability_tier.value,
            rule_key=rule.rule_key,
            rule_version=rule.version,
            quality=quality,
            source_record_id=observation.source_record_id,
        )
        key = make_risk_event_idempotency_key(patient_id, rule.rule_key, rule.version, observation.observed_at, [evidence.as_dict()])
        events.append(
            RiskEvaluation(
                patient_id=patient_id,
                severity=RiskSeverity.LOW,
                confidence=quality.quality_score,
                reason=f"{observation.metric_code} reading is stale; do not treat it as live deterioration.",
                evidence=(evidence,),
                rule=rule,
                idempotency_key=key,
                recommended_action="refresh_device_data",
                should_escalate_as_emergency=False,
            )
        )
    return events


def _effective_severity(base: RiskSeverity, quality: ObservationQuality) -> RiskSeverity:
    if quality.freshness == FreshnessStatus.STALE:
        return RiskSeverity.LOW
    if quality.freshness == FreshnessStatus.FUTURE_TIMESTAMP:
        return RiskSeverity.INFORMATIONAL
    if quality.reliability_tier == ReliabilityTier.MANUAL_OR_OCR and base == RiskSeverity.CRITICAL:
        return RiskSeverity.HIGH
    if quality.quality_score < 0.45 and SEVERITY_RANK[base] >= SEVERITY_RANK[RiskSeverity.HIGH]:
        return RiskSeverity.MODERATE
    return base


def _rule_matches(rule: RiskRule, observation: Observation) -> bool:
    condition = rule.conditions
    value = observation.value
    operator = condition.get("operator")
    if operator == "truthy":
        return bool(value)
    if not isinstance(value, (int, float, Decimal)):
        return False
    threshold = float(condition["value"])
    numeric = float(value)
    if operator == "<":
        return numeric < threshold
    if operator == "<=":
        return numeric <= threshold
    if operator == ">":
        return numeric > threshold
    if operator == ">=":
        return numeric >= threshold
    if operator == "==":
        return numeric == threshold
    raise ValueError(f"Unsupported rule operator: {operator}")


def _recommended_action(severity: RiskSeverity, requires_confirmation: bool, freshness: FreshnessStatus) -> str:
    if freshness == FreshnessStatus.STALE:
        return "refresh_device_data"
    if requires_confirmation:
        return "request_patient_confirmation"
    if severity == RiskSeverity.CRITICAL:
        return "start_escalation_protocol"
    if severity == RiskSeverity.HIGH:
        return "create_alert"
    if severity == RiskSeverity.MODERATE:
        return "notify_care_team"
    return "record_quality_notice"


def _reason_for(rule: RiskRule, observation: Observation, quality: ObservationQuality, severity: RiskSeverity) -> str:
    metric_name = {
        "spo2": "SpO2",
        "blood_glucose": "blood glucose",
        "continuous_glucose": "continuous glucose",
        "heart_rate": "heart rate",
        "fall_detected": "fall",
    }.get(observation.metric_code, observation.metric_code)
    reason = f"{metric_name} matched {rule.name} ({observation.value} {observation.unit or ''}) from {quality.reliability_tier.value}"
    if quality.freshness == FreshnessStatus.STALE:
        reason += "; reading is stale"
    if severity != rule.severity_value:
        reason += f"; severity reduced from {rule.severity_value.value} to {severity.value} because of source quality"
    return reason.strip()


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _require_datetime(value: str | datetime) -> datetime:
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError("datetime value is required")
    return parsed


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
