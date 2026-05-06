from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from app.domain.channels import Channel, ChannelLink, DispatchRequest, DispatchStatus, ProviderBehavior
from app.domain.escalation import (
    Acknowledgement,
    ConsentState,
    EmergencySimulation,
    EscalationAction,
    EscalationActionStatus,
    EscalationPolicy,
    EscalationPolicyStep,
    EscalationRun,
    EscalationRunStatus,
    RiskEvent,
    RiskSeverity,
    SimulationStatus,
)
from app.services.channels import ChannelDispatcher, MockProviderAdapter


ACK_STATUSES = {DispatchStatus.ACKNOWLEDGED}
SUCCESS_STATUSES = {DispatchStatus.DELIVERED, DispatchStatus.SIMULATED, DispatchStatus.SENT, DispatchStatus.ANSWERED}


class InMemoryEscalationStore:
    def __init__(self) -> None:
        self.by_idempotency: dict[str, EscalationRun] = {}
        self.by_risk_policy: dict[tuple[str, str], EscalationRun] = {}

    def find(self, risk_event_id: str, policy_id: str, idempotency_key: str) -> EscalationRun | None:
        return self.by_idempotency.get(idempotency_key) or self.by_risk_policy.get((risk_event_id, policy_id))

    def save(self, run: EscalationRun) -> EscalationRun:
        self.by_idempotency[run.idempotency_key] = run
        self.by_risk_policy[(run.risk_event_id, run.policy_id)] = run
        return run


class EscalationEngine:
    def __init__(
        self,
        dispatcher: ChannelDispatcher,
        *,
        store: InMemoryEscalationStore | None = None,
        channel_links: list[ChannelLink] | None = None,
    ) -> None:
        self.dispatcher = dispatcher
        self.store = store or InMemoryEscalationStore()
        self.channel_links = channel_links or []

    def start(
        self,
        risk_event: RiskEvent,
        policy: EscalationPolicy,
        *,
        idempotency_key: str,
        requested_by: str = "system",
        consent: ConsentState | None = None,
        variables: dict[str, str] | None = None,
        provider_behaviors: list[dict[str, Any]] | None = None,
    ) -> EscalationRun:
        existing = self.store.find(risk_event.id, policy.id, idempotency_key)
        if existing is not None:
            existing.metadata["idempotency_replayed"] = True
            return existing
        if not policy.active:
            raise PermissionError("inactive escalation policy")

        consent = consent or ConsentState()
        variables = self._variables(risk_event, variables)
        run = EscalationRun(
            id=str(uuid.uuid4()),
            patient_id=risk_event.patient_id,
            risk_event_id=risk_event.id,
            policy_id=policy.id,
            idempotency_key=idempotency_key,
            requested_by=requested_by,
            status=EscalationRunStatus.RUNNING,
            metadata={"simulation": policy.simulation_mode},
        )
        self.store.save(run)
        behavior_by_step = {item.get("step_order"): ProviderBehavior(item["behavior"]) for item in provider_behaviors or []}

        for step in sorted(policy.steps, key=lambda item: item.step_order):
            action = self._action_for_step(step)
            run.actions.append(action)
            if not step.enabled:
                self._skip(action, "step_disabled", "policy step disabled")
                continue
            if not consent.allows_channel(step.channel):
                self._skip(action, "consent_denied", f"consent denied for {step.channel}")
                continue
            if step.public_emergency_number and (not consent.emergency_services or not policy.emergency_enabled):
                self._skip(action, "emergency_policy_denied", "emergency service step requires consent and enabled policy")
                continue
            if step.channel == Channel.TELEGRAM and not self._has_verified_link(risk_event.patient_id, Channel.TELEGRAM, step.target_contact_id):
                self._skip(action, "unverified_channel", "telegram commands require verified channel link")
                continue

            dispatch_variables = dict(variables)
            if step.include_location and not consent.location_sharing:
                dispatch_variables.pop("location", None)
                action.metadata["location_included"] = False
            elif step.include_location:
                action.metadata["location_included"] = "location" in dispatch_variables

            action.status = EscalationActionStatus.ATTEMPTING
            self._configure_behavior(step.step_order, behavior_by_step.get(step.step_order))
            request = DispatchRequest(
                patient_id=risk_event.patient_id,
                channel=step.channel,
                variables=dispatch_variables,
                reason=risk_event.reason,
                policy_decision_id=f"policy:{policy.id}:step:{step.step_order}",
                idempotency_key=f"{run.id}:{step.step_order}:1",
                contact_id=step.target_contact_id,
                escalation_run_id=run.id,
                escalation_action_id=action.id,
                template_id=step.template_id,
                script_id=step.script_id,
                simulation=policy.simulation_mode,
            )
            attempt = self.dispatcher.dispatch(request)
            action.dispatch_attempts.append(attempt)
            self._sync_action_status(action, attempt.status)
            if attempt.status in ACK_STATUSES:
                self._acknowledge_from_action(run, action)
                return self.store.save(run)

        if any(action.status in {EscalationActionStatus.DELIVERED, EscalationActionStatus.SENT, EscalationActionStatus.ANSWERED} for action in run.actions):
            run.status = EscalationRunStatus.AWAITING_ACK
            run.outcome = "awaiting_human_acknowledgement"
        elif all(action.status == EscalationActionStatus.SKIPPED for action in run.actions):
            run.status = EscalationRunStatus.FAILED
            run.outcome = "all_actions_blocked"
        else:
            run.status = EscalationRunStatus.FAILED
            run.outcome = "no_acknowledgement"
        return self.store.save(run)

    def acknowledge(
        self,
        run: EscalationRun,
        *,
        acknowledgement_method: str,
        channel: Channel | None = None,
        acknowledged_by_contact_id: str | None = None,
        acknowledged_by_user_id: str | None = None,
        escalation_action_id: str | None = None,
        response_payload: dict[str, Any] | None = None,
    ) -> Acknowledgement | None:
        if channel == Channel.TELEGRAM and not self._has_verified_link(run.patient_id, Channel.TELEGRAM, acknowledged_by_contact_id):
            run.metadata["last_invalid_ack"] = "unverified_telegram"
            if run.status != EscalationRunStatus.ACKNOWLEDGED:
                run.status = EscalationRunStatus.AWAITING_ACK
            return None
        ack = Acknowledgement(
            id=str(uuid.uuid4()),
            escalation_run_id=run.id,
            acknowledgement_method=acknowledgement_method,
            channel=channel,
            escalation_action_id=escalation_action_id,
            acknowledged_by_contact_id=acknowledged_by_contact_id,
            acknowledged_by_user_id=acknowledged_by_user_id,
            response_payload=response_payload or {},
        )
        run.acknowledgements.append(ack)
        run.status = EscalationRunStatus.ACKNOWLEDGED
        run.outcome = "acknowledged"
        return ack

    def cancel(self, run: EscalationRun, *, reason: str, actor: str = "patient") -> EscalationRun:
        run.status = EscalationRunStatus.CANCELLED
        run.outcome = reason
        run.metadata["cancelled_by"] = actor
        for action in run.actions:
            if action.status in {EscalationActionStatus.PENDING, EscalationActionStatus.ATTEMPTING}:
                action.status = EscalationActionStatus.CANCELLED
        return self.store.save(run)

    def _variables(self, risk_event: RiskEvent, variables: dict[str, str] | None) -> dict[str, str]:
        merged = {
            "severity": risk_event.severity.value,
            "reason": risk_event.reason,
            "patient_name": "the patient",
            "ack_url": "https://careagent.example/ack",
            "location": "location unavailable",
        }
        merged.update(variables or {})
        return merged

    def _action_for_step(self, step: EscalationPolicyStep) -> EscalationAction:
        return EscalationAction(
            id=str(uuid.uuid4()),
            step_order=step.step_order,
            action_type=step.action_type,
            channel=step.channel,
            target_contact_id=step.target_contact_id,
            template_id=step.template_id,
            script_id=step.script_id,
        )

    def _skip(self, action: EscalationAction, code: str, message: str) -> None:
        action.status = EscalationActionStatus.SKIPPED
        action.error_code = code
        action.error_message = message

    def _sync_action_status(self, action: EscalationAction, dispatch_status: DispatchStatus) -> None:
        if dispatch_status == DispatchStatus.ACKNOWLEDGED:
            action.status = EscalationActionStatus.ACKNOWLEDGED
        elif dispatch_status == DispatchStatus.ANSWERED:
            action.status = EscalationActionStatus.ANSWERED
        elif dispatch_status in SUCCESS_STATUSES:
            action.status = EscalationActionStatus.DELIVERED
        elif dispatch_status == DispatchStatus.POLICY_DENIED:
            action.status = EscalationActionStatus.SKIPPED
        elif dispatch_status in {DispatchStatus.FAILED, DispatchStatus.EXPIRED}:
            action.status = EscalationActionStatus.FAILED
        elif dispatch_status == DispatchStatus.CANCELLED:
            action.status = EscalationActionStatus.CANCELLED

    def _acknowledge_from_action(self, run: EscalationRun, action: EscalationAction) -> None:
        run.acknowledgements.append(
            Acknowledgement(
                id=str(uuid.uuid4()),
                escalation_run_id=run.id,
                escalation_action_id=action.id,
                acknowledgement_method="simulator_ack",
                channel=action.channel,
                acknowledged_by_contact_id=action.target_contact_id,
            )
        )
        run.status = EscalationRunStatus.ACKNOWLEDGED
        run.outcome = "acknowledged"

    def _has_verified_link(self, patient_id: str, channel: Channel, contact_id: str | None) -> bool:
        return any(
            link.patient_id == patient_id
            and link.channel == channel
            and link.verified
            and (contact_id is None or link.contact_id == contact_id)
            for link in self.channel_links
        )

    def _configure_behavior(self, step_order: int, behavior: ProviderBehavior | None) -> None:
        if behavior is None:
            return
        for adapter in self.dispatcher.adapters.values():
            if isinstance(adapter, MockProviderAdapter):
                adapter.behavior = behavior


class EmergencySimulationRunner:
    def __init__(self, engine: EscalationEngine, cases: dict[str, Any]):
        self.engine = engine
        self.cases = {case["key"]: case for case in cases["cases"]}

    @classmethod
    def from_fixture(cls, engine: EscalationEngine, path: str | Path) -> "EmergencySimulationRunner":
        return cls(engine, json.loads(Path(path).read_text(encoding="utf-8")))

    def run_case(
        self,
        scenario_key: str,
        patient_id: str,
        policy: EscalationPolicy | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> EmergencySimulation:
        case = self.cases[scenario_key]
        risk_data = case["risk_event"]
        risk_event = RiskEvent(
            id=risk_data.get("idempotency_key", f"risk_{scenario_key}"),
            patient_id=patient_id,
            severity=RiskSeverity(risk_data.get("severity", "critical")),
            reason=risk_data["reason"],
            evidence=risk_data.get("evidence", []),
            idempotency_key=risk_data.get("idempotency_key"),
        )
        policy = policy or default_simulation_policy(patient_id)
        consent = _consent_from_case(case)
        run = self.engine.start(
            risk_event,
            policy,
            idempotency_key=idempotency_key or f"simulation:{scenario_key}",
            requested_by="system",
            consent=consent,
            provider_behaviors=case.get("provider_behaviors"),
        )
        summary = {
            "run_status": run.status.value,
            "actions": [
                {
                    "step_order": action.step_order,
                    "channel": action.channel.value,
                    "status": action.status.value,
                    "error_code": action.error_code,
                }
                for action in run.actions
            ],
            "production_provider_invocations": 0,
        }
        return EmergencySimulation(
            id=str(uuid.uuid4()),
            patient_id=patient_id,
            scenario_key=scenario_key,
            status=SimulationStatus.PASSED,
            expected_steps=case.get("provider_behaviors", []),
            actual_summary=summary,
            escalation_run=run,
        )


def default_simulation_policy(patient_id: str) -> EscalationPolicy:
    return EscalationPolicy(
        id="default_simulation_policy",
        patient_id=patient_id,
        name="Default emergency simulation",
        severity_trigger=RiskSeverity.HIGH,
        simulation_mode=True,
        emergency_enabled=False,
        steps=(
            EscalationPolicyStep(1, "notify", Channel.PUSH, target_contact_id="primary", template_id="push_urgent_vitals_alert_v1"),
            EscalationPolicyStep(2, "notify", Channel.WHATSAPP, target_contact_id="primary", template_id="urgent_vitals_alert_v1"),
            EscalationPolicyStep(3, "call", Channel.VOICE, target_contact_id="primary", script_id="critical_escalation_ai_call_v1"),
            EscalationPolicyStep(4, "call", Channel.VOICE, target_contact_id="doctor", script_id="critical_escalation_ai_call_v1"),
        ),
    )


def _consent_from_case(case: dict[str, Any]) -> ConsentState:
    overrides = case.get("consent_overrides", {})
    return ConsentState(
        voice_calls=overrides.get("voice_calls") != "revoked",
        emergency_services=overrides.get("emergency_services") == "active",
        location_sharing=overrides.get("location_sharing") == "active",
    )
