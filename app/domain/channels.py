from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Channel(StrEnum):
    PUSH = "push"
    IN_APP = "in_app"
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    SMS = "sms"
    VOICE = "voice"
    EMAIL = "email"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"


class MessageTemplateStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISABLED = "disabled"


class CallScriptStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    DISABLED = "disabled"


class DispatchStatus(StrEnum):
    QUEUED = "queued"
    POLICY_DENIED = "policy_denied"
    PROVIDER_PENDING = "provider_pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    ANSWERED = "answered"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    SIMULATED = "simulated"


class ProviderEnvironment(StrEnum):
    PRODUCTION = "production"
    SANDBOX = "sandbox"
    SIMULATION = "simulation"
    PROTOTYPE = "prototype"


class ProviderKind(StrEnum):
    WHATSAPP_CLOUD = "whatsapp_cloud"
    WHATSAPP_BSP = "whatsapp_bsp"
    PROTOTYPE_WHATSAPP_WEB = "prototype_whatsapp_web"
    TELEGRAM_BOT = "telegram_bot"
    FCM = "fcm"
    APNS = "apns"
    SMS_GATEWAY = "sms_gateway"
    VOICE_TWILIO = "voice_twilio"
    VOICE_EXOTEL = "voice_exotel"
    VOICE_PLIVO = "voice_plivo"
    EMAIL_SMTP = "email_smtp"
    MOCK_SIMULATOR = "mock_simulator"


class ProviderBehavior(StrEnum):
    DELIVER = "deliver"
    FAIL = "fail"
    TIMEOUT = "timeout"
    ANSWER = "answer"
    ACKNOWLEDGE = "acknowledge"


@dataclass(frozen=True)
class ProviderConfig:
    id: str
    channel: Channel
    kind: ProviderKind
    environment: ProviderEnvironment = ProviderEnvironment.SIMULATION
    active: bool = True
    prototype_only: bool = False
    capabilities: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.kind == ProviderKind.PROTOTYPE_WHATSAPP_WEB and not self.prototype_only:
            raise ValueError("prototype WhatsApp Web providers must be marked prototype_only")
        if self.environment == ProviderEnvironment.PRODUCTION and self.prototype_only:
            raise ValueError("prototype providers cannot run in production")


@dataclass(frozen=True)
class ChannelLink:
    id: str
    patient_id: str
    channel: Channel
    external_subject_ref: str
    verification_status: VerificationStatus = VerificationStatus.PENDING
    contact_id: str | None = None
    user_account_id: str | None = None
    commands_enabled: bool = False
    uploads_enabled: bool = False

    @property
    def verified(self) -> bool:
        return self.verification_status == VerificationStatus.VERIFIED


@dataclass(frozen=True)
class MessageTemplate:
    id: str
    channel: Channel
    category: str
    body: str
    variables: tuple[str, ...] = ()
    locale: str = "en-IN"
    version: int = 1
    status: MessageTemplateStatus = MessageTemplateStatus.APPROVED
    provider_template_name: str | None = None
    business_initiated: bool = False
    requires_approval: bool = False
    active: bool = True

    def validate_for_dispatch(self, simulation: bool) -> None:
        if not self.active or self.status == MessageTemplateStatus.DISABLED:
            raise ValueError(f"template {self.id} is disabled")
        if self.channel == Channel.WHATSAPP and self.business_initiated:
            if self.requires_approval and self.status != MessageTemplateStatus.APPROVED:
                raise PermissionError("whatsapp template is not approved for business-initiated use")
        if not simulation and self.status not in {MessageTemplateStatus.APPROVED}:
            raise PermissionError("production dispatch requires approved templates")


@dataclass(frozen=True)
class CallScript:
    id: str
    opening_text: str
    body_template: str
    ai_disclosure: str
    variables: tuple[str, ...] = ()
    locale: str = "en-IN"
    version: int = 1
    status: CallScriptStatus = CallScriptStatus.APPROVED
    dtmf_options: dict[str, str] = field(default_factory=dict)
    speech_intents: dict[str, list[str]] = field(default_factory=dict)
    max_duration_seconds: int = 120
    recording_allowed: bool = False
    transcript_allowed: bool = False
    active: bool = True

    def validate_for_dispatch(self) -> None:
        if not self.active or self.status != CallScriptStatus.APPROVED:
            raise PermissionError("voice calls require an approved active script")
        if "ai" not in self.ai_disclosure.lower():
            raise PermissionError("voice call scripts must disclose AI identity")


@dataclass(frozen=True)
class RenderedContent:
    template_id: str
    channel: Channel
    body: str
    variables: dict[str, str]


@dataclass
class DispatchRequest:
    patient_id: str
    channel: Channel
    variables: dict[str, str]
    reason: str
    policy_decision_id: str | None
    idempotency_key: str
    contact_id: str | None = None
    conversation_id: str | None = None
    escalation_run_id: str | None = None
    escalation_action_id: str | None = None
    template_id: str | None = None
    script_id: str | None = None
    locale: str = "en-IN"
    media_refs: list[dict[str, str]] = field(default_factory=list)
    simulation: bool = False


@dataclass
class DispatchAttempt:
    id: str
    patient_id: str
    channel: Channel
    status: DispatchStatus
    idempotency_key: str
    simulation: bool
    provider_config_id: str
    rendered_content: RenderedContent | None = None
    provider_message_id: str | None = None
    provider_call_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeliveryReceipt:
    dispatch_attempt_id: str
    patient_id: str
    channel: Channel
    event_type: str
    provider_status: str
    signature_valid: bool
    metadata: dict[str, Any] = field(default_factory=dict)

