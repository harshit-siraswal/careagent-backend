from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from app.core.audit import audit
from app.core.security import Actor, current_actor, optional_actor, require_patient_scope, require_permission
from app.schemas import (
    AcknowledgeRequest,
    AgentMessageRequest,
    AgentMessageResponse,
    AgentToolRequest,
    AgentToolResponse,
    Alert,
    AuthSessionRequest,
    AuthSessionResponse,
    CareTeamMember,
    CareTeamMemberCreateRequest,
    ConsentGrant,
    ConsentGrantRequest,
    Device,
    DeviceCatalogEntry,
    DeviceCreateRequest,
    DocumentDetailResponse,
    DocumentProcessingStatus,
    DocumentReviewRequest,
    DocumentUploadInitRequest,
    DocumentUploadInitResponse,
    DoseEventCreateRequest,
    EscalationPolicy,
    EscalationPolicyCreateRequest,
    EscalationRun,
    EscalationStartRequest,
    ExtractedMedicalFact,
    HealthResponse,
    ItemsResponse,
    LatestVitalsResponse,
    MeResponse,
    MedicalDocument,
    Medicine,
    MedicineCreateRequest,
    MedicineDoseEvent,
    MedicineSchedule,
    MedicineScheduleUpsertRequest,
    Observation,
    ObservationBatchCreateRequest,
    ObservationBatchCreateResponse,
    ObservationListResponse,
    PatientCreateRequest,
    PatientProfile,
    PatientQuestionRequest,
    PatientQuestionResponse,
    PatientSummary,
    PatientUpdateRequest,
    RevokeConsentRequest,
    RiskEvent,
    RiskEventCreateRequest,
    UploadTarget,
    VitalReading,
)
from app.schemas.common import utcnow
from app.services.care_data import care_repository

router = APIRouter()
AuthDep = Annotated[Actor, Depends(current_actor)]
OptionalAuthDep = Annotated[Actor, Depends(optional_actor)]


def _not_found(resource_type: str, resource_id: UUID) -> None:
    raise HTTPException(
        status_code=404,
        detail={
            "code": f"{resource_type}_not_found",
            "message": f"{resource_type.replace('_', ' ').title()} was not found.",
            "details": {"id": str(resource_id)},
        },
    )


def _parse_datetime_query(value: str | None, parameter: str) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_query_parameter",
                "message": f"{parameter} must be an ISO-8601 datetime.",
                "details": {"parameter": parameter},
            },
        ) from exc


@router.get("/health", response_model=HealthResponse, tags=["Health"])
def health() -> HealthResponse:
    return HealthResponse()


@router.post("/auth/session", response_model=AuthSessionResponse, tags=["Auth"])
def create_session(request: Request, body: AuthSessionRequest, actor: OptionalAuthDep) -> AuthSessionResponse:
    audit(request, actor=actor, action="auth.session_created", resource_type="auth_session")
    return AuthSessionResponse(access_token=f"stub-{uuid4()}", role=actor.role, user_id=actor.user_id)


@router.get("/me", response_model=MeResponse, tags=["Auth"])
def me(request: Request, actor: AuthDep) -> MeResponse:
    audit(request, actor=actor, action="auth.me_viewed", resource_type="user_account")
    grants = care_repository.list_actor_grants(actor.user_id)
    if actor.patient_id is not None:
        grants.insert(0, {"patient_id": actor.patient_id, "role": actor.role, "permissions": sorted(actor.permissions)})
    return MeResponse(id=actor.user_id, role=actor.role, grants=grants)


@router.post("/patients", response_model=PatientProfile, status_code=status.HTTP_201_CREATED, tags=["Patients"])
def create_patient(request: Request, body: PatientCreateRequest, actor: AuthDep) -> PatientProfile:
    require_permission(actor, "patient:write")
    patient = care_repository.create_patient(body, account_id=actor.user_id)
    audit(request, actor=actor, action="patient.profile_created", resource_type="patient_profile", patient_id=patient.id, phi_access=True)
    return patient


@router.get("/patients", response_model=ItemsResponse, tags=["Patients"])
def list_patients(request: Request, actor: AuthDep) -> ItemsResponse:
    require_permission(actor, "patient:read")
    audit(request, actor=actor, action="patient.roster_viewed", resource_type="patient_profile", patient_id=actor.patient_id, phi_access=True)
    return ItemsResponse(items=care_repository.list_patients(scoped_patient_id=actor.patient_id))


@router.get("/patients/{patient_id}", response_model=PatientProfile, tags=["Patients"])
def get_patient(request: Request, patient_id: UUID, actor: AuthDep) -> PatientProfile:
    require_patient_scope(actor, patient_id, "patient:read")
    audit(request, actor=actor, action="patient.profile_viewed", resource_type="patient_profile", patient_id=patient_id, phi_access=True)
    patient = care_repository.get_patient(patient_id)
    if patient is None:
        _not_found("patient", patient_id)
    return patient


@router.patch("/patients/{patient_id}", response_model=PatientProfile, tags=["Patients"])
def update_patient(request: Request, patient_id: UUID, body: PatientUpdateRequest, actor: AuthDep) -> PatientProfile:
    require_patient_scope(actor, patient_id, "patient:write")
    payload = body.model_dump(exclude_none=True)
    audit(request, actor=actor, action="patient.profile_updated", resource_type="patient_profile", patient_id=patient_id, phi_access=True, metadata={"fields": sorted(payload)})
    patient = care_repository.update_patient(patient_id, payload)
    if patient is None:
        _not_found("patient", patient_id)
    return patient


@router.get("/patients/{patient_id}/care-team", response_model=ItemsResponse, tags=["Patients"])
def list_care_team(request: Request, patient_id: UUID, actor: AuthDep) -> ItemsResponse:
    require_patient_scope(actor, patient_id, "care_team:read")
    audit(request, actor=actor, action="care_team.viewed", resource_type="care_team_member", patient_id=patient_id, phi_access=True)
    return ItemsResponse(items=[])


@router.post("/patients/{patient_id}/care-team", response_model=CareTeamMember, status_code=status.HTTP_201_CREATED, tags=["Patients"])
def add_care_team_member(request: Request, patient_id: UUID, body: CareTeamMemberCreateRequest, actor: AuthDep) -> CareTeamMember:
    require_patient_scope(actor, patient_id, "care_team:write")
    member = CareTeamMember(**body.model_dump(), patient_id=patient_id)
    audit(request, actor=actor, action="care_team.member_added", resource_type="care_team_member", patient_id=patient_id, resource_id=member.id, phi_access=True)
    return member


@router.get("/patients/{patient_id}/consents", response_model=ItemsResponse, tags=["Consent"])
def list_consents(request: Request, patient_id: UUID, actor: AuthDep) -> ItemsResponse:
    require_patient_scope(actor, patient_id, "consent:read")
    audit(request, actor=actor, action="consent.viewed", resource_type="consent_grant", patient_id=patient_id, phi_access=True)
    return ItemsResponse(items=care_repository.list_consents(patient_id))


@router.post("/patients/{patient_id}/consents", response_model=ConsentGrant, status_code=status.HTTP_201_CREATED, tags=["Consent"])
def grant_consent(request: Request, patient_id: UUID, body: ConsentGrantRequest, actor: AuthDep) -> ConsentGrant:
    require_patient_scope(actor, patient_id, "consent:write")
    consent = care_repository.grant_consent(patient_id, body)
    audit(request, actor=actor, action="consent.granted", resource_type="consent_grant", patient_id=patient_id, resource_id=consent.id, phi_access=True, reason=body.reason)
    return consent


@router.get("/patients/{patient_id}/consents/{consent_id}", response_model=ConsentGrant, tags=["Consent"])
def get_consent(request: Request, patient_id: UUID, consent_id: UUID, actor: AuthDep) -> ConsentGrant:
    require_patient_scope(actor, patient_id, "consent:read")
    audit(request, actor=actor, action="consent.viewed", resource_type="consent_grant", patient_id=patient_id, resource_id=consent_id, phi_access=True)
    consent = care_repository.get_consent(patient_id, consent_id)
    if consent is None:
        _not_found("consent", consent_id)
    return consent


@router.post("/patients/{patient_id}/consents/{consent_id}/revoke", response_model=ConsentGrant, tags=["Consent"])
def revoke_consent(request: Request, patient_id: UUID, consent_id: UUID, body: RevokeConsentRequest | None = None, actor: Actor = Depends(current_actor)) -> ConsentGrant:
    require_patient_scope(actor, patient_id, "consent:write")
    audit(request, actor=actor, action="consent.revoked", resource_type="consent_grant", patient_id=patient_id, resource_id=consent_id, phi_access=True, reason=body.reason if body else None)
    consent = care_repository.revoke_consent(patient_id, consent_id)
    if consent is None:
        _not_found("consent", consent_id)
    return consent


@router.get("/device-catalog", response_model=ItemsResponse, tags=["Devices"])
def device_catalog() -> ItemsResponse:
    return ItemsResponse(items=[DeviceCatalogEntry(brand="Generic", model="Manual Entry", category="manual", connection_methods=["manual"], supported_metrics=["heart_rate", "spo2", "blood_pressure"])])


@router.get("/patients/{patient_id}/devices", response_model=ItemsResponse, tags=["Devices"])
def list_devices(request: Request, patient_id: UUID, actor: AuthDep) -> ItemsResponse:
    require_patient_scope(actor, patient_id, "devices:read")
    audit(request, actor=actor, action="devices.viewed", resource_type="device", patient_id=patient_id, phi_access=True)
    return ItemsResponse(items=[])


@router.post("/patients/{patient_id}/devices", response_model=Device, status_code=status.HTTP_201_CREATED, tags=["Devices"])
def create_device(request: Request, patient_id: UUID, body: DeviceCreateRequest, actor: AuthDep) -> Device:
    require_patient_scope(actor, patient_id, "devices:write")
    device = Device(**body.model_dump(), patient_id=patient_id)
    audit(request, actor=actor, action="device.registered", resource_type="device", patient_id=patient_id, resource_id=device.id, phi_access=True)
    return device


@router.get("/patients/{patient_id}/observations", response_model=ObservationListResponse, tags=["Observations"])
def list_observations(
    request: Request,
    patient_id: UUID,
    actor: AuthDep,
    metric_code: str | None = None,
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: str | None = None,
    limit: int = 50,
) -> ObservationListResponse:
    require_patient_scope(actor, patient_id, "observations:read")
    audit(request, actor=actor, action="observations.queried", resource_type="observation", patient_id=patient_id, phi_access=True, metadata={"metric_code": metric_code, "from": from_, "to": to, "limit": limit})
    return ObservationListResponse(
        items=care_repository.list_observations(
            patient_id,
            metric_code=metric_code,
            observed_from=_parse_datetime_query(from_, "from"),
            observed_to=_parse_datetime_query(to, "to"),
            limit=limit,
        )
    )


@router.post("/patients/{patient_id}/observations", response_model=ObservationBatchCreateResponse, status_code=status.HTTP_202_ACCEPTED, tags=["Observations"])
def create_observations(request: Request, patient_id: UUID, body: ObservationBatchCreateRequest, actor: AuthDep) -> ObservationBatchCreateResponse:
    require_patient_scope(actor, patient_id, "observations:write")
    audit(request, actor=actor, action="observation.created", resource_type="observation", patient_id=patient_id, phi_access=True, metadata={"accepted_count": len(body.observations)})
    return care_repository.create_observations(patient_id, body)


@router.get("/patients/{patient_id}/observations/{observation_id}", response_model=Observation, tags=["Observations"])
def get_observation(request: Request, patient_id: UUID, observation_id: UUID, actor: AuthDep) -> Observation:
    require_patient_scope(actor, patient_id, "observations:read")
    audit(request, actor=actor, action="observation.viewed", resource_type="observation", patient_id=patient_id, resource_id=observation_id, phi_access=True)
    observation = care_repository.get_observation(patient_id, observation_id)
    if observation is None:
        _not_found("observation", observation_id)
    return observation


@router.get("/patients/{patient_id}/vitals/latest", response_model=LatestVitalsResponse, tags=["Observations"])
def latest_vitals(request: Request, patient_id: UUID, actor: AuthDep) -> LatestVitalsResponse:
    require_patient_scope(actor, patient_id, "observations:read")
    audit(request, actor=actor, action="vitals.latest_viewed", resource_type="observation", patient_id=patient_id, phi_access=True)
    return care_repository.latest_vitals(patient_id)


@router.get("/patients/{patient_id}/documents", response_model=ItemsResponse, tags=["Documents"])
def list_documents(request: Request, patient_id: UUID, actor: AuthDep) -> ItemsResponse:
    require_patient_scope(actor, patient_id, "documents:read")
    audit(request, actor=actor, action="documents.list_viewed", resource_type="medical_document", patient_id=patient_id, phi_access=True)
    return ItemsResponse(items=care_repository.list_documents(patient_id))


@router.post("/patients/{patient_id}/documents", response_model=DocumentUploadInitResponse, status_code=status.HTTP_201_CREATED, tags=["Documents"])
def init_document_upload(
    request: Request,
    patient_id: UUID,
    body: DocumentUploadInitRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    actor: AuthDep,
) -> DocumentUploadInitResponse:
    require_patient_scope(actor, patient_id, "documents:write")
    response = care_repository.init_document_upload(patient_id, body, idempotency_key=idempotency_key, actor_id=actor.user_id)
    audit(request, actor=actor, action="document.upload_session_created", resource_type="medical_document", patient_id=patient_id, resource_id=response.document.id, phi_access=True, metadata={"idempotency_key": idempotency_key})
    return response


@router.get("/patients/{patient_id}/documents/{document_id}", response_model=DocumentDetailResponse, tags=["Documents"])
def get_document(request: Request, patient_id: UUID, document_id: UUID, actor: AuthDep) -> DocumentDetailResponse:
    require_patient_scope(actor, patient_id, "documents:read")
    audit(request, actor=actor, action="document.viewed", resource_type="medical_document", patient_id=patient_id, resource_id=document_id, phi_access=True)
    detail = care_repository.get_document(patient_id, document_id)
    if detail is None:
        _not_found("document", document_id)
    return detail


@router.get("/patients/{patient_id}/documents/{document_id}/status", response_model=DocumentProcessingStatus, tags=["Documents"])
def document_status(request: Request, patient_id: UUID, document_id: UUID, actor: AuthDep) -> DocumentProcessingStatus:
    require_patient_scope(actor, patient_id, "documents:read")
    audit(request, actor=actor, action="document.status_viewed", resource_type="medical_document", patient_id=patient_id, resource_id=document_id, phi_access=True)
    processing_status = care_repository.document_status(patient_id, document_id)
    if processing_status is None:
        _not_found("document", document_id)
    return processing_status


@router.post("/patients/{patient_id}/documents/{document_id}/review", response_model=DocumentDetailResponse, tags=["Documents"])
def review_document(request: Request, patient_id: UUID, document_id: UUID, body: DocumentReviewRequest, actor: AuthDep) -> DocumentDetailResponse:
    require_patient_scope(actor, patient_id, "documents:write")
    audit(request, actor=actor, action="document.extraction_reviewed", resource_type="extracted_medical_fact", patient_id=patient_id, resource_id=document_id, phi_access=True, metadata={"fact_count": len(body.facts)})
    detail = care_repository.review_document(
        patient_id,
        document_id,
        [fact.model_dump(mode="json") for fact in body.facts],
    )
    if detail is None:
        _not_found("document", document_id)
    return detail


@router.post("/patients/{patient_id}/questions", response_model=PatientQuestionResponse, tags=["Documents"])
def answer_question(request: Request, patient_id: UUID, body: PatientQuestionRequest, actor: AuthDep) -> PatientQuestionResponse:
    require_patient_scope(actor, patient_id, "documents:read")
    audit_id = audit(request, actor=actor, action="document.question_answered", resource_type="agent_answer", patient_id=patient_id, phi_access=True, metadata={"allowed_document_count": len(body.allowed_document_ids or [])})
    return PatientQuestionResponse(answer="Stub answer pending document retrieval integration.", audit_log_id=audit_id)


@router.get("/patients/{patient_id}/medicines", response_model=ItemsResponse, tags=["Medicines"])
def list_medicines(request: Request, patient_id: UUID, actor: AuthDep) -> ItemsResponse:
    require_patient_scope(actor, patient_id, "medicines:read")
    audit(request, actor=actor, action="medicines.viewed", resource_type="medicine", patient_id=patient_id, phi_access=True)
    return ItemsResponse(items=care_repository.list_medicines(patient_id))


@router.post("/patients/{patient_id}/medicines", response_model=Medicine, status_code=status.HTTP_201_CREATED, tags=["Medicines"])
def create_medicine(request: Request, patient_id: UUID, body: MedicineCreateRequest, actor: AuthDep) -> Medicine:
    require_patient_scope(actor, patient_id, "medicines:write")
    medicine = care_repository.create_medicine(patient_id, body)
    audit(request, actor=actor, action="medicine.created", resource_type="medicine", patient_id=patient_id, resource_id=medicine.id, phi_access=True)
    return medicine


@router.get("/patients/{patient_id}/medicines/{medicine_id}", response_model=Medicine, tags=["Medicines"])
def get_medicine(request: Request, patient_id: UUID, medicine_id: UUID, actor: AuthDep) -> Medicine:
    require_patient_scope(actor, patient_id, "medicines:read")
    audit(request, actor=actor, action="medicine.viewed", resource_type="medicine", patient_id=patient_id, resource_id=medicine_id, phi_access=True)
    medicine = care_repository.get_medicine(patient_id, medicine_id)
    if medicine is None:
        _not_found("medicine", medicine_id)
    return medicine


@router.get("/patients/{patient_id}/medicine-schedule", response_model=ItemsResponse, tags=["Medicines"])
def list_medicine_schedule(request: Request, patient_id: UUID, actor: AuthDep) -> ItemsResponse:
    require_patient_scope(actor, patient_id, "medicines:read")
    audit(request, actor=actor, action="medicine_schedule.viewed", resource_type="medicine_schedule", patient_id=patient_id, phi_access=True)
    return ItemsResponse(items=care_repository.list_medicine_schedules(patient_id))


@router.post("/patients/{patient_id}/medicine-schedule", response_model=MedicineSchedule, tags=["Medicines"])
def upsert_medicine_schedule(request: Request, patient_id: UUID, body: MedicineScheduleUpsertRequest, actor: AuthDep) -> MedicineSchedule:
    require_patient_scope(actor, patient_id, "medicines:write")
    schedule = care_repository.upsert_medicine_schedule(patient_id, body)
    audit(request, actor=actor, action="medicine_schedule.upserted", resource_type="medicine_schedule", patient_id=patient_id, resource_id=schedule.id, phi_access=True)
    return schedule


@router.post("/patients/{patient_id}/dose-events", response_model=MedicineDoseEvent, status_code=status.HTTP_201_CREATED, tags=["Medicines"])
def record_dose_event(request: Request, patient_id: UUID, body: DoseEventCreateRequest, actor: AuthDep) -> MedicineDoseEvent:
    require_patient_scope(actor, patient_id, "medicines:write")
    dose = care_repository.record_dose_event(patient_id, body)
    audit(request, actor=actor, action="medicine_dose.recorded", resource_type="medicine_dose_event", patient_id=patient_id, resource_id=dose.id, phi_access=True)
    return dose


@router.post("/patients/{patient_id}/risk-events", response_model=RiskEvent, status_code=status.HTTP_201_CREATED, tags=["Risk"])
def create_risk_event(request: Request, patient_id: UUID, body: RiskEventCreateRequest, actor: AuthDep) -> RiskEvent:
    require_patient_scope(actor, patient_id, "risk:write")
    risk_event = care_repository.create_risk_event(patient_id, body)
    audit(request, actor=actor, action="risk_event.created", resource_type="risk_event", patient_id=patient_id, resource_id=risk_event.id, phi_access=True, reason=body.reason)
    return risk_event


@router.get("/patients/{patient_id}/alerts", response_model=ItemsResponse, tags=["Risk"])
def list_alerts(request: Request, patient_id: UUID, actor: AuthDep) -> ItemsResponse:
    require_patient_scope(actor, patient_id, "alerts:read")
    audit(request, actor=actor, action="alerts.viewed", resource_type="alert", patient_id=patient_id, phi_access=True)
    return ItemsResponse(items=care_repository.list_alerts(patient_id))


@router.post("/risk-events/{risk_event_id}/acknowledge", response_model=RiskEvent, tags=["Risk"])
def acknowledge_risk_event(
    request: Request,
    risk_event_id: UUID,
    body: AcknowledgeRequest | None = None,
    actor: Actor = Depends(current_actor),
    x_careagent_patient_id: Annotated[UUID | None, Header(alias="X-CareAgent-Patient-Id")] = None,
) -> RiskEvent:
    patient_id = x_careagent_patient_id or actor.patient_id or uuid4()
    require_patient_scope(actor, patient_id, "alerts:write")
    audit(request, actor=actor, action="risk_event.acknowledged", resource_type="risk_event", patient_id=patient_id, resource_id=risk_event_id, phi_access=True, metadata=body.model_dump(exclude_none=True) if body else {})
    risk_event = care_repository.acknowledge_risk_event(risk_event_id, patient_id)
    if risk_event is None:
        _not_found("risk_event", risk_event_id)
    return risk_event


@router.get("/patients/{patient_id}/escalation-policies", response_model=ItemsResponse, tags=["Escalation"])
def list_escalation_policies(request: Request, patient_id: UUID, actor: AuthDep) -> ItemsResponse:
    require_patient_scope(actor, patient_id, "escalation:read")
    audit(request, actor=actor, action="escalation_policies.viewed", resource_type="escalation_policy", patient_id=patient_id, phi_access=True)
    return ItemsResponse(items=care_repository.list_escalation_policies(patient_id))


@router.post("/patients/{patient_id}/escalation-policies", response_model=EscalationPolicy, status_code=status.HTTP_201_CREATED, tags=["Escalation"])
def create_escalation_policy(request: Request, patient_id: UUID, body: EscalationPolicyCreateRequest, actor: AuthDep) -> EscalationPolicy:
    require_patient_scope(actor, patient_id, "escalation:write")
    policy = care_repository.create_escalation_policy(patient_id, body, actor_id=actor.user_id)
    audit(request, actor=actor, action="escalation_policy.created", resource_type="escalation_policy", patient_id=patient_id, resource_id=policy.id, phi_access=True)
    return policy


@router.post("/risk-events/{risk_event_id}/escalate", response_model=EscalationRun, status_code=status.HTTP_201_CREATED, tags=["Escalation"])
def start_escalation(
    request: Request,
    risk_event_id: UUID,
    body: EscalationStartRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    actor: Actor = Depends(current_actor),
    x_careagent_patient_id: Annotated[UUID | None, Header(alias="X-CareAgent-Patient-Id")] = None,
) -> EscalationRun:
    patient_id = x_careagent_patient_id or actor.patient_id or uuid4()
    require_patient_scope(actor, patient_id, "escalation:write")
    run = care_repository.start_escalation(
        risk_event_id,
        patient_id,
        body,
        idempotency_key=idempotency_key,
        actor_id=actor.user_id,
    )
    audit(request, actor=actor, action="escalation.started", resource_type="escalation_run", patient_id=patient_id, resource_id=run.id, phi_access=True, reason=body.reason, metadata={"idempotency_key": idempotency_key, "simulation_mode": body.simulation_mode})
    return run


@router.get("/escalation-runs/{escalation_run_id}", response_model=EscalationRun, tags=["Escalation"])
def get_escalation_run(
    request: Request,
    escalation_run_id: UUID,
    actor: Actor = Depends(current_actor),
    x_careagent_patient_id: Annotated[UUID | None, Header(alias="X-CareAgent-Patient-Id")] = None,
) -> EscalationRun:
    patient_id = x_careagent_patient_id or actor.patient_id or uuid4()
    require_patient_scope(actor, patient_id, "escalation:read")
    audit(request, actor=actor, action="escalation_run.viewed", resource_type="escalation_run", patient_id=patient_id, resource_id=escalation_run_id, phi_access=True)
    run = care_repository.get_escalation_run(escalation_run_id, patient_id)
    if run is None:
        _not_found("escalation_run", escalation_run_id)
    return run


@router.post("/escalation-runs/{escalation_run_id}/acknowledge", response_model=EscalationRun, tags=["Escalation"])
def acknowledge_escalation_run(
    request: Request,
    escalation_run_id: UUID,
    body: AcknowledgeRequest | None = None,
    actor: Actor = Depends(current_actor),
    x_careagent_patient_id: Annotated[UUID | None, Header(alias="X-CareAgent-Patient-Id")] = None,
) -> EscalationRun:
    patient_id = x_careagent_patient_id or actor.patient_id or uuid4()
    require_patient_scope(actor, patient_id, "escalation:write")
    run = care_repository.acknowledge_escalation_run(
        escalation_run_id,
        patient_id,
        actor_id=actor.user_id,
        note=body.note if body else None,
    )
    if run is None:
        _not_found("escalation_run", escalation_run_id)
    audit(request, actor=actor, action="escalation.acknowledged", resource_type="escalation_run", patient_id=patient_id, resource_id=escalation_run_id, phi_access=True, metadata=body.model_dump(exclude_none=True) if body else {})
    return run


@router.post("/agent/messages", response_model=AgentMessageResponse, tags=["Agent"])
def agent_message(request: Request, body: AgentMessageRequest, actor: AuthDep) -> AgentMessageResponse:
    require_patient_scope(actor, body.patient_id, "agent:write")
    conversation_id = body.conversation_id or uuid4()
    audit_id = audit(request, actor=actor, action="agent.message_received", resource_type="message", patient_id=body.patient_id, phi_access=True, metadata={"channel": body.channel, "has_attachments": bool(body.attachments)})
    return AgentMessageResponse(conversation_id=conversation_id, response="Stub agent response pending orchestration integration.", audit_log_id=audit_id)


@router.post("/agent/tools/{tool_name}", response_model=AgentToolResponse, tags=["Agent"])
def agent_tool(tool_name: str, request: Request, body: AgentToolRequest, actor: AuthDep) -> AgentToolResponse:
    require_patient_scope(actor, body.patient_id, "agent:tool_call")
    audit_id = audit(request, actor=actor, action="agent.tool_called", resource_type="agent_tool_call", patient_id=body.patient_id, phi_access=True, reason=body.reason, metadata={"tool_name": tool_name, "authorization_scope": body.authorization_scope})
    return AgentToolResponse(result={"tool_name": tool_name, "status": "stubbed"}, audit_log_id=audit_id)


@router.get("/patients/{patient_id}/audit-logs", response_model=ItemsResponse, tags=["Audit"])
def list_audit_logs(request: Request, patient_id: UUID, actor: AuthDep, limit: int = 50) -> ItemsResponse:
    require_patient_scope(actor, patient_id, "audit:read")
    audit_id = audit(request, actor=actor, action="audit_logs.viewed", resource_type="audit_log", patient_id=patient_id, phi_access=True, metadata={"limit": limit})
    items = care_repository.list_audit_logs(patient_id, limit=limit)
    items.insert(0, {"id": audit_id, "action": "audit_logs.viewed", "patient_id": patient_id})
    return ItemsResponse(items=items)
